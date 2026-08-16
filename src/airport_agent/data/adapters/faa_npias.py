"""FAA NPIAS Appendix A adapter — the `npias` table (capital need + capacity constraint label).

Source: `https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/
ARP-NPIAS-2025-2029-AppendixA.xlsx` (2.3 MB, 3,287 airports; see
docs/research/2026-08-15-us-aviation-data-sources.md §5). The NPIAS is the FAA's own
five-year statement of what each airport in the national system needs to build, so
`dev_estimate_usd` is the only *authoritative* dollar figure of unmet capital need we have.

Verified 2026-08-15 against the real workbook:

* Sheet `All NPIAS Airports` (3,287 x 11) holds every airport; the remaining sheets are
  per-state slices of the same rows plus a `New Airports` sheet — only the first is read.
* Headers contain embedded newlines (`'Hub\\n(FY25)'`, `'Enplaned\\n(CY23/FY25)'`,
  `'Development\\nEstimate\\n2025-2029'`, and `' Based Aircraft\\n(FY25)'` with a leading
  space), so every header is whitespace-collapsed before lookup.
* `Hub (FY25)` is `L`/`M`/`S`/`N` for the 390 primary airports and empty for the other
  2,897 — mapped to the shared `large/medium/small/nonhub` vocabulary, empty → `None`
  (non-primary; the field is "no hub class", not "nonhub").
* `Enplaned (CY23/FY25)` and `Development Estimate 2025-2029` arrive as int64; both are
  cast to float for the store.

Capacity labels are *not* in Appendix A. They are joined from
`data/curated/npias_capacity_lists.yaml`, a hand transcription of Figure 1 "National
Capacity Outlook" (p. 9 of the NPIAS narrative PDF, a raster image), whose counts are
confirmed by the narrative text (11 constrained in 2028, 14 in 2033, 13 more congested).
The highest applicable label wins: 4 severe_2033 > 3 constrained_2028 > 2 constrained_2033
> 1 congested > 0 none. Airports absent from Figure 1 get 0, which means "not flagged by
the FAA evaluation" (the evaluation only covers large/medium hubs) — never "measured
uncongested".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage
from airport_agent.data.paths import curated_dir

NPIAS_EDITION = "2025-2029"
#: The edition's plan years, split out for the `SourceVintage` period.
NPIAS_PLAN_YEARS: tuple[str, str] = ("2025", "2029")
NPIAS_URL = (
    "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/"
    "ARP-NPIAS-2025-2029-AppendixA.xlsx"
)
NPIAS_FILENAME = "ARP-NPIAS-2025-2029-AppendixA.xlsx"

#: The sheet holding every airport; the other sheets are per-state slices of the same rows.
SHEET_NAME = "All NPIAS Airports"

#: Whitespace-collapsed header → output column.
SOURCE_COLUMNS: dict[str, str] = {
    "LocID": "faa_locid",
    "Hub (FY25)": "hub",
    "Enplaned (CY23/FY25)": "enplanements",
    "Development Estimate 2025-2029": "dev_estimate_usd",
}

#: NPIAS hub code → the shared `HubSize` vocabulary (empty = non-primary → None).
HUB_MAP: dict[str, str] = {"L": "large", "M": "medium", "S": "small", "N": "nonhub"}

#: Capacity label text → numeric label, highest first (the first list an airport is on wins).
CAPACITY_LABELS: tuple[tuple[str, int], ...] = (
    ("severe_2033", 4),
    ("constrained_2028", 3),
    ("constrained_2033", 2),
    ("congested", 1),
)
NO_CAPACITY_LABEL = (0, "none")

#: `npias` columns in store order.
NPIAS_COLUMNS: tuple[str, ...] = (
    "faa_locid",
    "hub",
    "enplanements",
    "dev_estimate_usd",
    "capacity_label",
    "capacity_label_text",
    "source_id",
    "vintage",
)

CAPACITY_LISTS_FILE = "npias_capacity_lists.yaml"

#: Figure 1 status wording → the list an airport belongs to for that horizon.
_FIGURE_STATUS = {"none", "congested", "constrained", "severe"}


@dataclass(frozen=True)
class CapacityLists:
    """The transcribed FAA capacity lists plus their provenance."""

    source_url: str
    as_of: str
    severe_2033: tuple[str, ...]
    constrained_2028: tuple[str, ...]
    constrained_2033: tuple[str, ...]
    congested: tuple[str, ...]
    figure_1_status: dict[str, dict[int, str]]

    def label_for(self, locid: str) -> tuple[int, str]:
        """Return `(label, label_text)` for `locid`; the highest applicable list wins."""
        for text, label in CAPACITY_LABELS:
            if locid in getattr(self, text):
                return label, text
        return NO_CAPACITY_LABEL

    def derived_lists(self) -> dict[str, list[str]]:
        """Rebuild the four lists from the verbatim `figure_1_status` transcription.

        Used by the tests to prove the lists the adapter reads are exactly what Figure 1
        shows, rather than a second, drifting hand-transcription.
        """
        severe = sorted(k for k, v in self.figure_1_status.items() if v[2033] == "severe")
        c2028 = sorted(
            k for k, v in self.figure_1_status.items() if v[2028] in {"constrained", "severe"}
        )
        c2033 = sorted(
            k for k, v in self.figure_1_status.items() if v[2033] in {"constrained", "severe"}
        )
        congested = sorted(set(self.figure_1_status) - set(c2033))
        return {
            "severe_2033": severe,
            "constrained_2028": c2028,
            "constrained_2033": c2033,
            "congested": congested,
        }


def load_capacity_lists(path: Path | None = None) -> CapacityLists:
    """Load `data/curated/npias_capacity_lists.yaml` (or `path`) and validate its shape."""
    src = path or (curated_dir() / CAPACITY_LISTS_FILE)
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    status = {
        str(locid): {int(year): str(value) for year, value in years.items()}
        for locid, years in raw["figure_1_status"].items()
    }
    bad = {v for years in status.values() for v in years.values()} - _FIGURE_STATUS
    if bad:
        raise ValueError(f"{src.name}: unknown figure_1_status value(s) {sorted(bad)}")
    return CapacityLists(
        source_url=str(raw["source_url"]),
        as_of=str(raw["as_of"]),
        severe_2033=tuple(raw["severe_2033"]),
        constrained_2028=tuple(raw["constrained_2028"]),
        constrained_2033=tuple(raw["constrained_2033"]),
        congested=tuple(raw["congested"]),
        figure_1_status=status,
    )


def _collapse(header: object) -> str:
    """Collapse the newlines/padding the FAA puts inside Appendix A headers."""
    return re.sub(r"\s+", " ", str(header)).strip()


def read_appendix_a(path: Path) -> pd.DataFrame:
    """Read the `All NPIAS Airports` sheet with whitespace-collapsed headers."""
    df = pd.read_excel(path, sheet_name=SHEET_NAME, dtype={"LocID": str})
    df.columns = [_collapse(c) for c in df.columns]
    missing = [c for c in SOURCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing Appendix A column(s) {missing}")
    return df


@register
class FaaNpiasAdapter:
    """Fetch/normalize NPIAS Appendix A into `npias`, labelled with the FAA capacity lists."""

    id: str = "faa_npias"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self, capacity_lists: CapacityLists | None = None) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw file's own date.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._capacity_lists = capacity_lists

    @property
    def capacity_lists(self) -> CapacityLists:
        """The curated FAA capacity lists (loaded once, on first use)."""
        if self._capacity_lists is None:
            self._capacity_lists = load_capacity_lists()
        return self._capacity_lists

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download Appendix A (cached). `period` is ignored: one edition covers 2025-2029."""
        path = download(NPIAS_URL, cache_dir, filename=NPIAS_FILENAME)
        self._set_vintage([path])
        return [path]

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"npias": df}` with the columns of the store's `npias` table."""
        if len(paths) != 1:
            raise ValueError(f"faa_npias expects exactly one Appendix A file, got {len(paths)}")
        self._set_vintage(paths)
        raw = read_appendix_a(paths[0])

        locid = raw["LocID"].astype(str).str.strip()
        labels = [self.capacity_lists.label_for(code) for code in locid]
        out = pd.DataFrame(
            {
                "faa_locid": locid,
                "hub": raw["Hub (FY25)"].astype(str).str.strip().map(HUB_MAP),
                "enplanements": pd.to_numeric(raw["Enplaned (CY23/FY25)"], errors="coerce").astype(float),
                "dev_estimate_usd": pd.to_numeric(
                    raw["Development Estimate 2025-2029"], errors="coerce"
                ).astype(float),
                "capacity_label": [label for label, _ in labels],
                "capacity_label_text": [text for _, text in labels],
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        out["capacity_label"] = out["capacity_label"].astype("int64")
        return {"npias": out[list(NPIAS_COLUMNS)].sort_values("faa_locid").reset_index(drop=True)}

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw file's mtime (see `file_vintage`)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw file's date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        lists = self.capacity_lists
        return SourceVintage(
            source_id=self.id,
            description=(
                f"FAA NPIAS {NPIAS_EDITION} Appendix A — hub class, CY23 enplanements and the "
                "5-year development estimate, with capacity-constraint labels from the NPIAS "
                f"national capacity outlook ({lists.source_url}, as of {lists.as_of})"
            ),
            period_start=NPIAS_PLAN_YEARS[0],
            period_end=NPIAS_PLAN_YEARS[1],
            fetched_at=self._fetched_at,
            url=NPIAS_URL,
        )
