"""Census CBSA population + gazetteer centroid adapter — the `catchment` table.

Sources (both keyless bulk downloads, no auth; see
docs/research/2026-08-15-us-aviation-data-sources.md, "Avoid for a one-day
build" — this adapter deliberately uses the bulk CSVs it recommends instead of
the keyed Census/BEA APIs):

* Population estimates — Population Estimates Program, two non-overlapping
  vintage files so history reaches back to 2010:
  `https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv`
  (`POPESTIMATE2020..2025`) and
  `https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/metro/totals/cbsa-est2019-alldata.csv`
  (`POPESTIMATE2010..2019`).
* Centroids — 2024 Census Gazetteer CBSA file:
  `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cbsa_national.zip`
  (`GEOID, NAME, CBSA_TYPE, INTPTLAT, INTPTLONG`).

**RESCOPE (2026-08-16): population + centroids only, no BEA.** `catchment.
gdp_real_usd` is always `None`; only the `cbsa_population`/`cbsa_pop_cagr_5y`
metrics are computable from this source, not `msa_gdp_per_capita`/
`msa_gdp_cagr_5y`.

Verified 2026-08-16 against the real files:

* Both population files share one column shape: `CBSA, MDIV, STCOU, NAME,
  LSAD, ...POPESTIMATE<year>...` (`latin-1`-encoded — a handful of county names
  have accented characters that raise `UnicodeDecodeError` under `utf-8`).
  `LSAD == "Metropolitan Statistical Area"` alone is **not** enough to isolate
  one row per metro: a Metropolitan Division sub-row (e.g. "Boston, MA" inside
  CBSA 14460 "Boston-Cambridge-Newton, MA-NH") carries the *same* `LSAD` value
  and the *same* `CBSA` code as its parent metro row — the only field that
  tells them apart is `MDIV` (non-null on the division sub-row, null on the
  true top-level metro row). County-level component rows use a different
  `LSAD` ("County or equivalent") and are already excluded by the `LSAD`
  filter. The correct filter is therefore `LSAD == "Metropolitan Statistical
  Area" AND MDIV.isna()` — 387 rows in the 2025 file, one per real metro CBSA.
* The Gazetteer file is tab-separated (not comma) with `CBSA_TYPE`: `1` =
  Metro, `2` = Micro — filter `CBSA_TYPE == 1`. `GEOID` matches the population
  file's `CBSA` code exactly (verified: Boston = `14460` in both).

Airport -> CBSA is a **nearest-centroid join within 100 miles**, not a formal
catchment boundary (known-limitations row 32): `apply_cbsa_enrichment` reads
`airports.lat/lon` from the store, finds the nearest metro centroid within
`max_distance_mi` (default 100) via `geo.haversine_mi`, writes it into
`airports.cbsa_code`/`airports.cbsa_name` (an UPDATE, like
`faa_taf.apply_taf_enrichment` — not a `replace_rows`, since `catchment`'s
identity source is `airports`, not this adapter), and expands the per-CBSA
population series into per-iata `catchment` rows. `normalize()` alone cannot
do this join: it has no access to `airports.lat/lon`, only the raw files.
"""
from __future__ import annotations

import calendar
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from airport_agent.contracts.models import SourceVintage
from airport_agent.data.adapters import register
from airport_agent.data.adapters.base import Period, download, file_vintage
from airport_agent.data.geo import haversine_mi
from airport_agent.data.store import Store

#: Two non-overlapping population-estimate vintages (2010-2019 gives history the
#: current 2020-2025 vintage does not carry).
POPULATION_URLS: dict[str, str] = {
    "2020-2025": (
        "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/"
        "cbsa-est2025-alldata.csv"
    ),
    "2010-2019": (
        "https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/metro/totals/"
        "cbsa-est2019-alldata.csv"
    ),
}
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
    "2024_Gaz_cbsa_national.zip"
)
GAZETTEER_MEMBER = "2024_Gaz_cbsa_national.txt"

_POP_YEAR_RE = re.compile(r"^POPESTIMATE(\d{4})$")

#: Gazetteer `CBSA_TYPE` code for a true metropolitan (as opposed to micropolitan) area.
METRO_CBSA_TYPE = 1

#: Default airport -> CBSA join radius (design 01 / plan Task 10).
DEFAULT_MAX_DISTANCE_MI = 100.0

CBSA_POPULATION_COLUMNS: tuple[str, ...] = ("cbsa_code", "cbsa_name", "year", "population", "source_id", "vintage")
CBSA_CENTROID_COLUMNS: tuple[str, ...] = ("cbsa_code", "cbsa_name", "lat", "lon", "source_id", "vintage")
#: `catchment` columns in store order (see plan Store schema). `gdp_real_usd` is always None
#: (no BEA source in this RESCOPE).
CATCHMENT_COLUMNS: tuple[str, ...] = (
    "iata",
    "cbsa_code",
    "cbsa_name",
    "year",
    "population",
    "gdp_real_usd",
    "source_id",
    "vintage",
)


def _read_population_csv(path: Path) -> pd.DataFrame:
    """Return long-format `(cbsa_code, cbsa_name, year, population)` for true metro CBSAs."""
    raw = pd.read_csv(path, dtype={"CBSA": str, "MDIV": str, "STCOU": str}, encoding="latin-1")
    metro = raw[(raw["LSAD"] == "Metropolitan Statistical Area") & raw["MDIV"].isna()]
    year_cols = [c for c in metro.columns if _POP_YEAR_RE.fullmatch(c)]
    long = metro.melt(
        id_vars=["CBSA", "NAME"], value_vars=year_cols, var_name="col", value_name="population"
    )
    long["year"] = long["col"].str.extract(r"(\d{4})").astype(int)
    long["population"] = pd.to_numeric(long["population"], errors="coerce")
    return long.rename(columns={"CBSA": "cbsa_code", "NAME": "cbsa_name"})[
        ["cbsa_code", "cbsa_name", "year", "population"]
    ]


def _read_gazetteer(path: Path) -> pd.DataFrame:
    """Return `(cbsa_code, cbsa_name, lat, lon)` for true metro (not micro) CBSAs."""
    raw = pd.read_csv(path, sep="\t", dtype={"GEOID": str})
    raw.columns = [c.strip() for c in raw.columns]
    metro = raw[pd.to_numeric(raw["CBSA_TYPE"], errors="coerce") == METRO_CBSA_TYPE]
    return pd.DataFrame(
        {
            "cbsa_code": metro["GEOID"].astype(str).str.strip(),
            "cbsa_name": metro["NAME"].astype(str).str.strip(),
            "lat": pd.to_numeric(metro["INTPTLAT"], errors="coerce"),
            "lon": pd.to_numeric(metro["INTPTLONG"], errors="coerce"),
        }
    )


def _nearest_cbsa(
    lat: float, lon: float, centroids: pd.DataFrame, max_distance_mi: float
) -> tuple[str, str] | None:
    """Return `(cbsa_code, cbsa_name)` of the nearest centroid within `max_distance_mi`, else `None`."""
    best: tuple[str, str] | None = None
    best_dist = max_distance_mi
    for row in centroids.itertuples(index=False):
        dist = haversine_mi(lat, lon, row.lat, row.lon)
        if dist <= best_dist:
            best = (row.cbsa_code, row.cbsa_name)
            best_dist = dist
    return best


def apply_cbsa_enrichment(
    store: Store,
    population: pd.DataFrame,
    centroids: pd.DataFrame,
    max_distance_mi: float = DEFAULT_MAX_DISTANCE_MI,
) -> None:
    """Join every `airports` row to its nearest metro CBSA and write `catchment` rows.

    An UPDATE of `airports.cbsa_code`/`cbsa_name` (like `faa_taf.apply_taf_enrichment` —
    `airports`' identity source is OurAirports, this only fills two columns it cannot know)
    plus a `replace_rows("catchment", ..., where={"source_id": "census_cbsa"})` expanding the
    per-CBSA population series into one row per (iata, year). Airports with no centroid
    within `max_distance_mi` get no `catchment` rows and keep `cbsa_code IS NULL` (never a
    guessed nearest-anyway match).
    """
    airports = store.con.execute("SELECT iata, lat, lon FROM airports").df()
    if airports.empty or centroids.empty:
        return
    source_id, vintage = "census_cbsa", (population["vintage"].iloc[0] if len(population) else None)
    matches = []
    for row in airports.itertuples(index=False):
        if row.lat is None or row.lon is None or pd.isna(row.lat) or pd.isna(row.lon):
            continue
        hit = _nearest_cbsa(row.lat, row.lon, centroids, max_distance_mi)
        if hit is not None:
            matches.append({"iata": row.iata, "cbsa_code": hit[0], "cbsa_name": hit[1]})
    match_df = pd.DataFrame(matches, columns=["iata", "cbsa_code", "cbsa_name"])
    if match_df.empty:
        return

    store.con.register("_cbsa_match", match_df)
    try:
        store.con.execute(
            """
            UPDATE airports
            SET cbsa_code = t.cbsa_code, cbsa_name = t.cbsa_name
            FROM _cbsa_match t
            WHERE airports.iata = t.iata
            """
        )
    finally:
        store.con.unregister("_cbsa_match")

    catchment = match_df.merge(population[["cbsa_code", "year", "population"]], on="cbsa_code", how="left")
    catchment["gdp_real_usd"] = None
    catchment["source_id"] = source_id
    catchment["vintage"] = vintage
    out = catchment.dropna(subset=["year"])[list(CATCHMENT_COLUMNS)]
    store.replace_rows("catchment", out, where={"source_id": source_id})


@register
class CensusCbsaAdapter:
    """Fetch/normalize Census CBSA population + gazetteer centroids."""

    id: str = "census_cbsa"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw files' own dates
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._period_start: str | None = None
        self._period_end: str | None = None

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download both population vintages and the gazetteer (cached). `period` is ignored."""
        pop_paths = [
            download(url, cache_dir, filename=f"cbsa_pop_{key}.csv") for key, url in POPULATION_URLS.items()
        ]
        gaz_zip = download(GAZETTEER_URL, cache_dir, filename="cbsa_gazetteer.zip")
        gaz_txt = self._extract_gazetteer(gaz_zip, Path(cache_dir) / GAZETTEER_MEMBER)
        paths = [*pop_paths, gaz_txt]
        self._set_vintage(paths)
        return paths

    @staticmethod
    def _extract_gazetteer(zip_path: Path, dest: Path) -> Path:
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        with zipfile.ZipFile(zip_path) as zf:
            info = zf.getinfo(GAZETTEER_MEMBER)
            part = dest.with_suffix(dest.suffix + ".part")
            try:
                with zf.open(GAZETTEER_MEMBER) as src, part.open("wb") as fh:
                    while chunk := src.read(1 << 20):
                        fh.write(chunk)
                part.replace(dest)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
        stamp = calendar.timegm((*info.date_time, 0, 0, -1))
        os.utime(dest, (stamp, stamp))
        return dest

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"cbsa_population": df, "cbsa_centroids": df}` (feed `apply_cbsa_enrichment`)."""
        self._set_vintage(paths)
        pop_paths = [p for p in paths if p.suffix.lower() == ".csv"]
        gaz_paths = [p for p in paths if p.suffix.lower() == ".txt"]
        if len(gaz_paths) != 1:
            raise ValueError(f"expected exactly one gazetteer .txt file, got {[p.name for p in gaz_paths]}")

        pop_frames = [_read_population_csv(p) for p in pop_paths]
        population = (
            pd.concat(pop_frames, ignore_index=True).drop_duplicates(["cbsa_code", "year"])
            if pop_frames
            else pd.DataFrame(columns=["cbsa_code", "cbsa_name", "year", "population"])
        )
        centroids = _read_gazetteer(gaz_paths[0])

        self._period_start = str(int(population["year"].min())) if len(population) else None
        self._period_end = str(int(population["year"].max())) if len(population) else None

        population["source_id"] = self.id
        population["vintage"] = self.row_vintage()
        centroids["source_id"] = self.id
        centroids["vintage"] = self.row_vintage()
        return {
            "cbsa_population": population[list(CBSA_POPULATION_COLUMNS)]
            .sort_values(["cbsa_code", "year"])
            .reset_index(drop=True),
            "cbsa_centroids": centroids[list(CBSA_CENTROID_COLUMNS)]
            .sort_values("cbsa_code")
            .reset_index(drop=True),
        }

    # -- provenance ----------------------------------------------------------
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
                "Census Bureau CBSA population estimates (2010-2019 + 2020-2025 vintages) and "
                "Gazetteer CBSA centroids — population + geography only, no BEA (RESCOPE)"
            ),
            period_start=self._period_start,
            period_end=self._period_end,
            fetched_at=self._fetched_at,
            url=POPULATION_URLS["2020-2025"],
        )
