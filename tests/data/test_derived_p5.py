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
    """cpe_usd / nonaero_rev_per_enpl / aip_per_enpl_10y — FAA CATS/AIP cut by the RESCOPE."""

    @pytest.mark.parametrize("metric_id", ["cpe_usd", "nonaero_rev_per_enpl", "aip_per_enpl_10y"])
    def test_always_empty(self, tmp_store: Store, metric_id: str) -> None:
        fn = METRIC_FUNCS[metric_id]
        assert fn(tmp_store.con, "12m", 2026, "2026-04").empty
        assert metric_id in MISSING_REASONS
