"""OurAirports adapter — the `airports` and `runways` base tables.

Source: `https://davidmegginson.github.io/ourairports-data/` (public domain,
rebuilt nightly; see docs/research/2026-08-15-us-aviation-data-sources.md §6).
It is the identity spine of the store: IATA/ICAO/FAA LocID, name, city, state,
lat/lon and the physical runway inventory. Fields this source cannot know
(`faa_region`, `hub_size`, `cbsa_*`, `commercial`) are written as documented
placeholders here and filled by later sources (TAF, NPIAS, Census/BEA, BTS).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage

BASE_URL = "https://davidmegginson.github.io/ourairports-data"
AIRPORTS_URL = f"{BASE_URL}/airports.csv"
RUNWAYS_URL = f"{BASE_URL}/runways.csv"

#: Airport types kept — everything that can plausibly carry scheduled service.
KEPT_TYPES: tuple[str, ...] = ("large_airport", "medium_airport", "small_airport")

#: `airports` columns in store order (see plan Store schema).
AIRPORT_COLUMNS: tuple[str, ...] = (
    "iata",
    "icao",
    "faa_locid",
    "name",
    "city",
    "state",
    "faa_region",
    "hub_size",
    "lat",
    "lon",
    "cbsa_code",
    "cbsa_name",
    "commercial",
    "source_id",
    "vintage",
)

#: `runways` columns in store order.
RUNWAY_COLUMNS: tuple[str, ...] = (
    "faa_locid",
    "runway_id",
    "length_ft",
    "width_ft",
    "surface",
    "closed",
    "source_id",
    "vintage",
)


def _read_csv(path: Path) -> pd.DataFrame:
    """Read an OurAirports CSV as all-text, with missing values as empty strings."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def _split(paths: list[Path]) -> tuple[Path, Path]:
    """Return (airports_path, runways_path) from a `fetch` result, by file name."""
    runways = [p for p in paths if "runway" in p.name.lower()]
    airports = [p for p in paths if "runway" not in p.name.lower()]
    if len(runways) != 1 or len(airports) != 1:
        raise ValueError(f"expected one airports and one runways file, got {[p.name for p in paths]}")
    return airports[0], runways[0]


@register
class OurAirportsAdapter:
    """Fetch/normalize the OurAirports airport and runway inventories."""

    id: str = "ourairports"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw files' own dates
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download both CSVs (cached on disk). `period` is ignored: the files are a full nightly snapshot."""
        paths = [
            download(AIRPORTS_URL, cache_dir, filename="ourairports_airports.csv"),
            download(RUNWAYS_URL, cache_dir, filename="ourairports_runways.csv"),
        ]
        self._set_vintage(paths)
        return paths

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"airports": df, "runways": df}` matching the store schema."""
        airports_path, runways_path = _split(paths)
        self._set_vintage(paths)
        raw_airports = _read_csv(airports_path)
        keep = raw_airports[
            raw_airports["type"].isin(KEPT_TYPES)
            & (raw_airports["iso_country"] == "US")
            & (raw_airports["iata_code"].str.strip() != "")
        ]
        airports = self._airports_frame(keep)
        runways = self._runways_frame(_read_csv(runways_path), keep)
        return {"airports": airports, "runways": runways}

    @staticmethod
    def _icao(keep: pd.DataFrame) -> pd.Series:
        """ICAO code: the dedicated `icao_code` column, else `ident`, else `gps_code`.

        `icao_code` is the authoritative field (added upstream after the research note was
        written); `ident` equals it for every airport that has a real ICAO code, but is a
        local designator (e.g. "16A" where `icao_code` is "PPIT") for ~12% of the kept US
        rows. `gps_code` is the last resort when both are blank.
        """
        icao = keep["icao_code"].str.strip()
        ident = keep["ident"].str.strip()
        gps = keep["gps_code"].str.strip()
        return icao.where(icao != "", ident.where(ident != "", gps))

    def _airports_frame(self, keep: pd.DataFrame) -> pd.DataFrame:
        iata = keep["iata_code"].str.strip()
        local = keep["local_code"].str.strip()
        out = pd.DataFrame(
            {
                "iata": iata,
                "icao": self._icao(keep),
                "faa_locid": local.where(local != "", iata),
                "name": keep["name"].str.strip(),
                "city": keep["municipality"].str.strip(),
                # iso_region is "US-MA" -> state "MA".
                "state": keep["iso_region"].str.strip().str.slice(3),
                "faa_region": "",  # filled by the FAA TAF adapter
                "hub_size": "nonhub",  # filled by the FAA TAF/NPIAS adapters
                "lat": pd.to_numeric(keep["latitude_deg"], errors="coerce"),
                "lon": pd.to_numeric(keep["longitude_deg"], errors="coerce"),
                "cbsa_code": None,  # filled by the Census/BEA adapter
                "cbsa_name": None,
                "commercial": False,  # set by traffic sources (BTS/TAF)
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        out["cbsa_code"] = out["cbsa_code"].astype("object")
        out["cbsa_name"] = out["cbsa_name"].astype("object")
        out["commercial"] = out["commercial"].astype(bool)
        return out[list(AIRPORT_COLUMNS)].sort_values("iata").reset_index(drop=True)

    def _runways_frame(self, raw_runways: pd.DataFrame, keep: pd.DataFrame) -> pd.DataFrame:
        local = keep["local_code"].str.strip()
        locid = local.where(local != "", keep["iata_code"].str.strip())
        locid_by_ident = dict(zip(keep["ident"].str.strip(), locid, strict=True))
        mine = raw_runways[raw_runways["airport_ident"].str.strip().isin(locid_by_ident)]
        out = pd.DataFrame(
            {
                "faa_locid": mine["airport_ident"].str.strip().map(locid_by_ident),
                "runway_id": mine["le_ident"].str.strip(),
                "length_ft": pd.to_numeric(mine["length_ft"], errors="coerce").astype("Int64"),
                "width_ft": pd.to_numeric(mine["width_ft"], errors="coerce").astype("Int64"),
                "surface": mine["surface"].str.strip(),
                "closed": mine["closed"].str.strip() == "1",
                "source_id": self.id,
                "vintage": self.row_vintage(),
            }
        )
        return out[list(RUNWAY_COLUMNS)].sort_values(["faa_locid", "runway_id"]).reset_index(drop=True)

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw files' mtimes (cached download => file's date)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw files' date ("YYYY-MM-DD"). The files carry no period of their own."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description="OurAirports airports + runways (public domain, rebuilt nightly)",
            period_start=None,
            period_end=None,
            fetched_at=self._fetched_at,
            url=AIRPORTS_URL,
        )
