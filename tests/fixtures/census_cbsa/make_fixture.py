"""Rebuild the committed Census CBSA fixture subset (needs network; not run by tests).

Usage: uv run python tests/fixtures/census_cbsa/make_fixture.py

Downloads the real population (2010-2019 + 2020-2025) and Gazetteer files once
(cached under `data/raw/`), keeps only the 13 CBSAs the 15 fixture airports
actually fall within 100 mi of (computed by nearest-centroid, the same method
`apply_cbsa_enrichment` uses), and writes the trimmed CSVs/TXT next to this
file. Rows are copied verbatim — county and metropolitan-division sub-rows for
those 13 CBSAs are kept too, so the fixture still exercises the
LSAD/MDIV filter the adapter relies on.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from airport_agent.data.adapters.census_cbsa import (
    GAZETTEER_MEMBER,
    POPULATION_URLS,
    CensusCbsaAdapter,
    _read_gazetteer,
)
from airport_agent.data.geo import haversine_mi
from airport_agent.data.paths import raw_cache_dir

HERE = Path(__file__).resolve().parent

FIXTURE_IATAS = [
    "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "LAX", "SNA",
    "SFO", "BUR", "ANC", "JFK", "ATL", "DEN", "ORD",
]


def _fixture_cbsa_codes(gaz_path: Path) -> set[str]:
    """The real nearest-CBSA (<=100mi) for each of the 15 fixture airports' real coordinates."""
    airports = pd.read_csv(
        Path(__file__).resolve().parents[1] / "ourairports" / "airports.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture = airports[airports["iata_code"].isin(FIXTURE_IATAS)]
    centroids = _read_gazetteer(gaz_path)
    codes: set[str] = set()
    for _, row in fixture.iterrows():
        lat, lon = float(row["latitude_deg"]), float(row["longitude_deg"])

        def _dist(c: pd.Series, lat: float = lat, lon: float = lon) -> float:
            return haversine_mi(lat, lon, c["lat"], c["lon"])

        dists = centroids.assign(d=centroids.apply(_dist, axis=1))
        nearest = dists.sort_values("d").iloc[0]
        if nearest["d"] <= 100.0:
            codes.add(nearest["cbsa_code"])
    return codes


def main() -> None:
    adapter = CensusCbsaAdapter()
    adapter.fetch(None, raw_cache_dir())
    pop_paths = {key: raw_cache_dir() / f"cbsa_pop_{key}.csv" for key in POPULATION_URLS}
    gaz_path = raw_cache_dir() / GAZETTEER_MEMBER

    codes = _fixture_cbsa_codes(gaz_path)
    print(f"fixture CBSA codes ({len(codes)}): {sorted(codes)}")

    for key, path in pop_paths.items():
        raw = pd.read_csv(path, dtype={"CBSA": str, "MDIV": str, "STCOU": str}, encoding="latin-1")
        sub = raw[raw["CBSA"].isin(codes)]
        out = HERE / f"cbsa_pop_{key}.csv"
        sub.to_csv(out, index=False, encoding="utf-8")
        print(f"wrote {out.name}: {len(sub)} rows, {out.stat().st_size // 1024} KB")

    gaz_raw = pd.read_csv(gaz_path, sep="\t", dtype={"GEOID": str})
    gaz_raw.columns = [c.strip() for c in gaz_raw.columns]
    # Keep the fixture CBSAs plus a couple of real Micropolitan rows so the CBSA_TYPE
    # filter has something real to exclude.
    micro = gaz_raw[pd.to_numeric(gaz_raw["CBSA_TYPE"], errors="coerce") == 2].head(2)
    gaz_sub = pd.concat([gaz_raw[gaz_raw["GEOID"].isin(codes)], micro])
    out = HERE / GAZETTEER_MEMBER
    gaz_sub.to_csv(out, sep="\t", index=False, encoding="utf-8")
    print(f"wrote {out.name}: {len(gaz_sub)} rows, {out.stat().st_size // 1024} KB")

    missing = codes - set(gaz_sub["GEOID"])
    if missing:
        raise SystemExit(f"missing CBSA codes in gazetteer subset: {missing}")


if __name__ == "__main__":
    main()
