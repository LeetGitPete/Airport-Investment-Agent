"""FAA Terminal Area Forecast adapter — `taf_history`, `taf_forecast`, hub/region enrichment.

Source: `https://taf.faa.gov/Downloads/APO100_TAF_Final_2025.zip` (TAF 2025 edition, no
auth; see docs/research/2026-08-15-us-aviation-data-sources.md §4). The TAF is the FAA's
own 30-year per-airport demand forecast, so it carries both the actual history and the
forecast used by the expansion-need metrics.

Three members of the zip are used:

* `Enplanements.xlsx` (`locid, scenario, ayear, aac, aat, commuter, us_flag, frgn_flag`,
  1976-2055). There is **no** total column: `aac` = domestic air carrier, `aat` = air taxi,
  `commuter` = commuter, `us_flag` / `frgn_flag` = international on US / foreign flag
  carriers. Total enplanements = the sum of all five (verified against BOS/LAX/ATL 2024,
  which land within a few percent of published traffic).
* `AirportsOperations.xlsx` (`itn_Ac, itn_at, itn_ga, itn_mil, loc_ga, loc_mil, tot_overs`,
  1990-2055). `ops_total` = the six itinerant + local columns. `tot_overs` (overflights) is
  excluded: those aircraft never touch the runway and must not inflate a capacity metric.
* `Airports.xlsx` (`LOCID, REGION, HUB_SIZE, ...`) — the FAA region code and the numeric hub
  class (3/2/1/0 → large/medium/small/nonhub), used to enrich the `airports` table.

History vs forecast is split on the file's own `scenario` marker (0 = actual, 1 = forecast);
the base year is read from the data as `min(ayear where scenario = 1)` (2025 in this
edition), never hard-coded — `DOCUMENTED_BASE_YEAR` is only a fallback if the marker is
absent. Enplanement years run back further than operations years, so the two are joined with
an outer join: pre-1990 rows keep their enplanements and a null `ops_total`.

The `"airports"` frame this adapter returns is an **enrichment** frame (`faa_locid,
hub_size, faa_region`), not a replacement for the `airports` table. Write it with
`apply_taf_enrichment(store, df)` (an UPDATE), never with `Store.replace_rows`.
"""
from __future__ import annotations

import calendar
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage
from airport_agent.data.store import Store

TAF_EDITION = "2025"
TAF_ZIP_URL = f"https://taf.faa.gov/Downloads/APO100_TAF_Final_{TAF_EDITION}.zip"
ZIP_FILENAME = f"APO100_TAF_Final_{TAF_EDITION}.zip"

#: Zip members this adapter extracts, in the order `fetch` returns them.
MEMBER_FILES: tuple[str, ...] = ("Airports.xlsx", "Enplanements.xlsx", "AirportsOperations.xlsx")

#: Fallback only — the real base year is read from the `scenario` marker in the data.
DOCUMENTED_BASE_YEAR = 2025

#: Enplanement components; their sum is total enplanements (the file has no total column).
ENPLANEMENT_COMPONENTS: tuple[str, ...] = ("aac", "aat", "commuter", "us_flag", "frgn_flag")

#: Operations components; `tot_overs` (overflights) is deliberately excluded.
OPERATION_COMPONENTS: tuple[str, ...] = ("itn_Ac", "itn_at", "itn_ga", "itn_mil", "loc_ga", "loc_mil")

#: FAA numeric hub class → the `airports.hub_size` vocabulary.
HUB_SIZE_MAP: dict[int, str] = {3: "large", 2: "medium", 1: "small", 0: "nonhub"}

#: `taf_history` / `taf_forecast` columns in store order.
TAF_COLUMNS: tuple[str, ...] = (
    "faa_locid",
    "year",
    "enplanements",
    "ops_total",
    "source_id",
    "vintage",
)

#: Columns of the `airports` enrichment frame (applied with `apply_taf_enrichment`).
ENRICHMENT_COLUMNS: tuple[str, ...] = ("faa_locid", "hub_size", "faa_region", "source_id", "vintage")


def _read_excel(path: Path, locid_column: str) -> pd.DataFrame:
    """Read a TAF workbook and strip the FAA's fixed-width padding from the LocID column."""
    df = pd.read_excel(path, dtype={locid_column: str})
    df[locid_column] = df[locid_column].astype(str).str.strip()
    return df


def _by_name(paths: list[Path]) -> dict[str, Path]:
    """Map each expected member file name to its path in `paths` (order-independent)."""
    found = {member: [p for p in paths if p.name == member] for member in MEMBER_FILES}
    missing = [member for member, hits in found.items() if len(hits) != 1]
    if missing:
        raise ValueError(f"expected one file per TAF member, missing/ambiguous: {missing}")
    return {member: hits[0] for member, hits in found.items()}


def apply_taf_enrichment(store: Store, df: pd.DataFrame) -> None:
    """Update `airports.hub_size` / `airports.faa_region` from a TAF enrichment frame.

    An UPDATE, not a replace: the `airports` row (and its `source_id`/`vintage`, which
    describe the identity source) belongs to OurAirports; the TAF only fills the two
    columns that source cannot know. Airports absent from `df` are left untouched and no
    rows are inserted or deleted, so this is safe to run repeatedly.
    """
    if len(df) == 0:
        return
    enrichment = df[["faa_locid", "hub_size", "faa_region"]]
    store.con.register("_taf_enrichment", enrichment)
    try:
        store.con.execute(
            """
            UPDATE airports
            SET hub_size = t.hub_size, faa_region = t.faa_region
            FROM _taf_enrichment t
            WHERE airports.faa_locid = t.faa_locid
            """
        )
    finally:
        store.con.unregister("_taf_enrichment")


@register
class FaaTafAdapter:
    """Fetch/normalize the FAA Terminal Area Forecast actuals, forecast and hub/region labels."""

    id: str = "faa_taf"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw files' own dates
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._period_start: str | None = None
        self._period_end: str | None = None
        self.base_year: int = DOCUMENTED_BASE_YEAR

    # fetch
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download the TAF zip (cached) and extract the three members into `cache_dir`.

        `period` is ignored: one TAF edition covers 1976-2055 in a single file.
        """
        zip_path = download(TAF_ZIP_URL, cache_dir, filename=ZIP_FILENAME)
        paths = [self._extract(zip_path, member, cache_dir) for member in MEMBER_FILES]
        self._set_vintage(paths)
        return paths

    @staticmethod
    def _extract(zip_path: Path, member: str, cache_dir: Path) -> Path:
        """Extract one member, reusing an existing non-empty file; mtime = the zip entry's date.

        Stamping the extracted file with the zip entry's own timestamp keeps `file_vintage`
        describing the FAA's publication, not the moment we happened to unzip, and makes
        repeated extraction idempotent.
        """
        dest = cache_dir / member
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        cache_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            info = zf.getinfo(member)
            part = dest.with_suffix(dest.suffix + ".part")
            try:
                with zf.open(member) as src, part.open("wb") as fh:
                    while chunk := src.read(1 << 20):
                        fh.write(chunk)
                part.replace(dest)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
        # Zip stores a naive local timestamp; read it as UTC so the vintage date is
        # the same on every host.
        stamp = calendar.timegm((*info.date_time, 0, 0, -1))
        os.utime(dest, (stamp, stamp))
        return dest

    # normalize
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"taf_history": df, "taf_forecast": df, "airports": df}`."""
        files = _by_name(paths)
        self._set_vintage(paths)

        enplanements = self._enplanements_frame(_read_excel(files["Enplanements.xlsx"], "locid"))
        operations = self._operations_frame(_read_excel(files["AirportsOperations.xlsx"], "locid"))
        annual = enplanements.merge(operations, on=["faa_locid", "year"], how="outer")
        annual["scenario"] = annual["scenario_x"].fillna(annual["scenario_y"])
        self.base_year = self._read_base_year(annual)
        self._period_start = str(int(annual["year"].min()))
        self._period_end = str(int(annual["year"].max()))

        history = self._taf_frame(annual[annual["year"] < self.base_year])
        forecast = self._taf_frame(annual[annual["year"] >= self.base_year])
        airports = self._airports_frame(_read_excel(files["Airports.xlsx"], "LOCID"))
        return {"taf_history": history, "taf_forecast": forecast, "airports": airports}

    @staticmethod
    def _read_base_year(annual: pd.DataFrame) -> int:
        """First forecast year = `min(ayear)` where the file's `scenario` marker is 1."""
        forecast_years = annual.loc[annual["scenario"] == 1, "year"]
        if forecast_years.empty:
            return DOCUMENTED_BASE_YEAR
        return int(forecast_years.min())

    @staticmethod
    def _enplanements_frame(raw: pd.DataFrame) -> pd.DataFrame:
        components = raw[list(ENPLANEMENT_COMPONENTS)].apply(pd.to_numeric, errors="coerce")
        return pd.DataFrame(
            {
                "faa_locid": raw["locid"],
                "year": pd.to_numeric(raw["ayear"], errors="coerce").astype("Int64"),
                "scenario": pd.to_numeric(raw["scenario"], errors="coerce"),
                "enplanements": components.sum(axis=1, min_count=1).astype(float),
            }
        )

    @staticmethod
    def _operations_frame(raw: pd.DataFrame) -> pd.DataFrame:
        components = raw[list(OPERATION_COMPONENTS)].apply(pd.to_numeric, errors="coerce")
        return pd.DataFrame(
            {
                "faa_locid": raw["locid"],
                "year": pd.to_numeric(raw["ayear"], errors="coerce").astype("Int64"),
                "scenario": pd.to_numeric(raw["scenario"], errors="coerce"),
                "ops_total": components.sum(axis=1, min_count=1).astype(float),
            }
        )

    def _taf_frame(self, annual: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "faa_locid": annual["faa_locid"],
                "year": annual["year"].astype("Int64"),
                "enplanements": annual["enplanements"].astype(float),
                "ops_total": annual["ops_total"].astype(float),
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        return out[list(TAF_COLUMNS)].sort_values(["faa_locid", "year"]).reset_index(drop=True)

    def _airports_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        hub = pd.to_numeric(raw["HUB_SIZE"], errors="coerce")
        out = pd.DataFrame(
            {
                "faa_locid": raw["LOCID"],
                "hub_size": hub.map(HUB_SIZE_MAP).fillna("nonhub"),
                "faa_region": raw["REGION"].astype(str).str.strip(),
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        return out[list(ENRICHMENT_COLUMNS)].sort_values("faa_locid").reset_index(drop=True)

    # provenance
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw files' mtimes (see `file_vintage`)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw files' date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                f"FAA Terminal Area Forecast (TAF {TAF_EDITION}) — actual and forecast "
                "enplanements and operations, plus hub class and FAA region"
            ),
            period_start=self._period_start,
            period_end=self._period_end,
            fetched_at=self._fetched_at,
            url=TAF_ZIP_URL,
        )
