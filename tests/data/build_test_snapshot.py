"""Build a tiny DuckDB snapshot from the committed fixture files (runs in seconds).

Every adapter's `normalize()` is run against its own fixture, written into a fresh
`Store`, then `build_derived` computes the registry on top — exactly the pipeline
`refresh.py` runs against real downloads, just on real-but-tiny subsets. Used by
`tests/data/conftest_plugin.py` (registers the `duckdb` contract-suite factory) and by
`tests/data/test_derived_*.py`.
"""
from __future__ import annotations

from pathlib import Path

from airport_agent.data.adapters.bts_otp import BtsOtpAdapter
from airport_agent.data.adapters.bts_socrata import BtsSocrataAdapter
from airport_agent.data.adapters.bts_t100 import BtsT100SegmentAdapter
from airport_agent.data.adapters.census_cbsa import CensusCbsaAdapter, apply_cbsa_enrichment
from airport_agent.data.adapters.curated import CuratedFactsAdapter
from airport_agent.data.adapters.faa_npias import FaaNpiasAdapter
from airport_agent.data.adapters.faa_taf import FaaTafAdapter, apply_taf_enrichment
from airport_agent.data.adapters.ourairports import OurAirportsAdapter
from airport_agent.data.derived import build_derived
from airport_agent.data.store import Store

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def build_test_snapshot(path: Path) -> Path:
    """Build (or overwrite) a DuckDB file at `path` from the committed fixtures; return `path`.

    The caller owns the connection lifecycle: this function closes its own write
    connection before returning so a read-only `DuckDBDataService` can open the same
    file afterwards (DuckDB allows only one writer at a time).
    """
    store = Store(path)

    oa_dir = FIXTURES_DIR / "ourairports"
    oa_adapter = OurAirportsAdapter()
    oa = oa_adapter.normalize([oa_dir / "airports.csv", oa_dir / "runways.csv"])
    store.replace_rows("airports", oa["airports"], None)
    store.replace_rows("runways", oa["runways"], None)
    store.upsert_vintage(oa_adapter.vintage())

    taf_dir = FIXTURES_DIR / "faa_taf"
    taf_adapter = FaaTafAdapter()
    taf = taf_adapter.normalize(
        [taf_dir / "Airports.xlsx", taf_dir / "Enplanements.xlsx", taf_dir / "AirportsOperations.xlsx"]
    )
    store.replace_rows("taf_history", taf["taf_history"], None)
    store.replace_rows("taf_forecast", taf["taf_forecast"], None)
    apply_taf_enrichment(store, taf["airports"])
    store.upsert_vintage(taf_adapter.vintage())

    npias_adapter = FaaNpiasAdapter()
    npias = npias_adapter.normalize([FIXTURES_DIR / "faa_npias" / "appendix_a_subset.xlsx"])
    store.replace_rows("npias", npias["npias"], None)
    store.upsert_vintage(npias_adapter.vintage())

    curated_adapter = CuratedFactsAdapter()
    curated = curated_adapter.normalize([FIXTURES_DIR / "curated" / "airport_facts_small.yaml"])
    store.replace_rows("curated_facts", curated["curated_facts"], None)
    store.replace_rows("curated_inputs", curated["curated_inputs"], None)
    store.upsert_vintage(curated_adapter.vintage())

    socrata_adapter = BtsSocrataAdapter()
    socrata = socrata_adapter.normalize([FIXTURES_DIR / "bts_socrata" / "sample.json"])
    store.replace_rows("airport_month", socrata["airport_month"], {"source_id": "bts_socrata"})
    store.replace_rows("airport_year", socrata["airport_year"], {"source_id": "bts_socrata"})
    store.upsert_vintage(socrata_adapter.vintage())

    # Two files: the single-month (2026-04) subset for all 15 fixture airports plus 5 more
    # months for BOS/SFO/ANC only (see make_fixture_extra_months.py) so `spill_proxy`
    # (needs >=6 months/route) is computable for the airports the contract suite checks.
    t100_adapter = BtsT100SegmentAdapter()
    t100 = t100_adapter.normalize(
        [
            FIXTURES_DIR / "bts_t100" / "dom_2026_04_subset.csv",
            FIXTURES_DIR / "bts_t100" / "dom_extra_months_subset.csv",
        ]
    )
    store.replace_rows("routes_month", t100["routes_month"], {"source_id": "bts_t100"})
    store.upsert_vintage(t100_adapter.vintage())

    otp_adapter = BtsOtpAdapter()
    otp = otp_adapter.normalize([FIXTURES_DIR / "bts_otp" / "otp_2026_06_subset.csv"])
    store.replace_rows("airport_month", otp["airport_month"], {"source_id": "bts_otp"})
    store.replace_rows("otp_taxi_hist", otp["otp_taxi_hist"], None)
    store.replace_rows("otp_peak", otp["otp_peak"], None)
    store.upsert_vintage(otp_adapter.vintage())

    census_dir = FIXTURES_DIR / "census_cbsa"
    census_adapter = CensusCbsaAdapter()
    census = census_adapter.normalize(
        [
            census_dir / "cbsa_pop_2020-2025.csv",
            census_dir / "cbsa_pop_2010-2019.csv",
            census_dir / "2024_Gaz_cbsa_national.txt",
        ]
    )
    apply_cbsa_enrichment(store, census["cbsa_population"], census["cbsa_centroids"])
    store.upsert_vintage(census_adapter.vintage())

    build_derived(store)
    store.close()
    return path
