"""P5 Financeability & Pipeline derived-metric tests."""
from __future__ import annotations

import pandas as pd
import pytest

from airport_agent.data.derived import METRIC_FUNCS, MISSING_REASONS, p5_finance
from airport_agent.data.store import Store


class TestNpiasDevPerEnpl:
    def test_dollars_per_enplanement(self, tmp_store: Store) -> None:
        tmp_store.con.execute(
            "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
            "commercial, source_id, vintage) VALUES ('AAA', 'AAA', 'x', 'x', 'XX', 'XXX', 'small', 0, 0, "
            "false, 'ourairports', '2026-01-01')"
        )
        tmp_store.replace_rows(
            "npias",
            pd.DataFrame(
                [{"faa_locid": "AAA", "hub": "small", "enplanements": 500_000.0, "dev_estimate_usd": 25_000_000.0,
                  "capacity_label": 0, "capacity_label_text": "none", "source_id": "faa_npias", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p5_finance.npias_dev_per_enpl(tmp_store.con, "forecast", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        assert row["value"] == pytest.approx(50.0)

    def test_zero_enplanements_excluded(self, tmp_store: Store) -> None:
        tmp_store.con.execute(
            "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
            "commercial, source_id, vintage) VALUES ('AAA', 'AAA', 'x', 'x', 'XX', 'XXX', 'small', 0, 0, "
            "false, 'ourairports', '2026-01-01')"
        )
        tmp_store.replace_rows(
            "npias",
            pd.DataFrame(
                [{"faa_locid": "AAA", "hub": None, "enplanements": 0.0, "dev_estimate_usd": 1_000.0,
                  "capacity_label": 0, "capacity_label_text": "none", "source_id": "faa_npias", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p5_finance.npias_dev_per_enpl(tmp_store.con, "forecast", 2026, "2026-04")
        assert df.empty


class TestCutSourcesAlwaysEmpty:
    """cpe_usd / nonaero_rev_per_enpl — no FAA CATS adapter, so both are always absent."""

    @pytest.mark.parametrize("metric_id", ["cpe_usd", "nonaero_rev_per_enpl"])
    def test_always_empty(self, tmp_store: Store, metric_id: str) -> None:
        fn = METRIC_FUNCS[metric_id]
        assert fn(tmp_store.con, "12m", 2026, "2026-04").empty
        assert metric_id in MISSING_REASONS


class TestAipPerEnpl10y:
    """`aip_per_enpl_10y` — computed for real once the
    `faa_aip` adapter landed; no longer in `MISSING_REASONS`."""

    def _seed_airport(self, store: Store) -> None:
        store.con.execute(
            "INSERT INTO airports (iata, faa_locid, name, city, state, faa_region, hub_size, lat, lon, "
            "commercial, source_id, vintage) VALUES ('AAA', 'AAA', 'x', 'x', 'XX', 'XXX', 'small', 0, 0, "
            "false, 'ourairports', '2026-01-01')"
        )

    def test_not_in_missing_reasons(self) -> None:
        assert "aip_per_enpl_10y" not in MISSING_REASONS

    def test_dollars_per_enplanement_over_10_fiscal_years(self, tmp_store: Store) -> None:
        self._seed_airport(tmp_store)
        tmp_store.replace_rows(
            "aip_grants",
            pd.DataFrame(
                [
                    {"faa_locid": "AAA", "fy": fy, "amount_usd": 1_000_000.0, "source_id": "faa_aip", "vintage": "2026-08"}
                    for fy in range(2017, 2027)
                ]
            ),
            None,
        )
        tmp_store.replace_rows(
            "airport_year",
            pd.DataFrame(
                [{"iata": "AAA", "year": 2026, "measure": "enplanements", "value": 500_000.0,
                  "source_id": "bts_socrata", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p5_finance.aip_per_enpl_10y(tmp_store.con, "10y", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        # 10 fiscal years (2017..2026) x $1,000,000 / 500,000 enplanements = $20/enplanement.
        assert row["value"] == pytest.approx(20.0)
        assert row["source_id"] == "faa_aip"
        assert row["period_start"] == "2017"
        assert row["period_end"] == "2026"

    def test_only_grants_within_the_10y_window_count(self, tmp_store: Store) -> None:
        self._seed_airport(tmp_store)
        tmp_store.replace_rows(
            "aip_grants",
            pd.DataFrame(
                [
                    {"faa_locid": "AAA", "fy": 2005, "amount_usd": 9_000_000.0, "source_id": "faa_aip", "vintage": "2026-08"},
                    {"faa_locid": "AAA", "fy": 2026, "amount_usd": 1_000_000.0, "source_id": "faa_aip", "vintage": "2026-08"},
                ]
            ),
            None,
        )
        tmp_store.replace_rows(
            "airport_year",
            pd.DataFrame(
                [{"iata": "AAA", "year": 2026, "measure": "enplanements", "value": 100_000.0,
                  "source_id": "bts_socrata", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p5_finance.aip_per_enpl_10y(tmp_store.con, "10y", 2026, "2026-04")
        row = df[df["iata"] == "AAA"].iloc[0]
        # Only the FY2026 grant is inside [2017, 2026]; the FY2005 grant is out of window.
        assert row["value"] == pytest.approx(10.0)

    def test_no_grants_in_window_yields_no_row(self, tmp_store: Store) -> None:
        self._seed_airport(tmp_store)
        tmp_store.replace_rows(
            "aip_grants",
            pd.DataFrame(
                [{"faa_locid": "AAA", "fy": 2000, "amount_usd": 1.0, "source_id": "faa_aip", "vintage": "2026-08"}]
            ),
            None,
        )
        df = p5_finance.aip_per_enpl_10y(tmp_store.con, "10y", 2026, "2026-04")
        assert df.empty
