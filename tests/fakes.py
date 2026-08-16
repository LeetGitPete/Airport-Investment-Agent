"""FakeDataService — deterministic canned data implementing the DataService Protocol. No I/O.

Values are plausible and internally consistent with docs/research/2026-08-15-airport-investment-metrics.md
and docs/research/2026-08-15-us-aviation-data-sources.md (verified Apr 2026 figures where they exist:
LAX 12.9 / SNA 13.9 / SFO 18.0 min avg departure delay; SFO load factor 0.80; ANC long-haul share 0.30;
NPIAS 2025-29 constraint labels; CPE and non-aero revenue per enplanement inverting with hub class).
They are test fixtures, not facts — never quote them outside tests.
"""
from __future__ import annotations

from airport_agent.contracts import (
    AirportFilter,
    AirportProfile,
    AirportRef,
    CuratedFact,
    FeatureMatrix,
    LiveStatus,
    Metric,
    MetricSpec,
    RouteRow,
    RouteTable,
    SourceVintage,
    load_registry,
)
from airport_agent.contracts.models import Horizon, PeerGroup

FETCHED = "2026-08-15T00:00:00"
VINT = "2026-04"

_A = [  # iata, icao, name, city, state, region, hub, lat, lon
    ("BOS", "KBOS", "Logan International", "Boston", "MA", "ANE", "large", 42.36, -71.01),
    ("BDL", "KBDL", "Bradley International", "Windsor Locks", "CT", "ANE", "medium", 41.94, -72.68),
    ("PVD", "KPVD", "T. F. Green", "Providence", "RI", "ANE", "small", 41.73, -71.43),
    ("MHT", "KMHT", "Manchester-Boston Regional", "Manchester", "NH", "ANE", "small", 42.93, -71.44),
    ("PWM", "KPWM", "Portland International Jetport", "Portland", "ME", "ANE", "small", 43.65, -70.31),
    ("LAX", "KLAX", "Los Angeles International", "Los Angeles", "CA", "AWP", "large", 33.94, -118.41),
    ("SNA", "KSNA", "John Wayne", "Santa Ana", "CA", "AWP", "medium", 33.68, -117.87),
    ("SFO", "KSFO", "San Francisco International", "San Francisco", "CA", "AWP", "large", 37.62, -122.38),
    ("BUR", "KBUR", "Hollywood Burbank", "Burbank", "CA", "AWP", "medium", 34.20, -118.36),
    ("ANC", "PANC", "Ted Stevens Anchorage International", "Anchorage", "AK", "AAL", "medium", 61.17, -150.0),
    ("JFK", "KJFK", "John F. Kennedy International", "New York", "NY", "AEA", "large", 40.64, -73.78),
    ("ATL", "KATL", "Hartsfield-Jackson Atlanta International", "Atlanta", "GA", "ASO", "large", 33.64, -84.43),
    ("DEN", "KDEN", "Denver International", "Denver", "CO", "ANM", "large", 39.86, -104.67),
]
AIRPORTS = [AirportRef(iata=i, icao=c, faa_locid=i, name=n, city=ci, state=s, faa_region=r, hub_size=h, lat=la, lon=lo)
            for i, c, n, ci, s, r, h, la, lo in _A]

CAGR_IDS = {"enpl_cagr_3y": 0.9, "enpl_cagr_5y": 1.0, "enpl_cagr_10y": 0.6}  # multipliers on BASE["enpl_cagr"]
LABEL_MAP = {0: "none", 1: "congested", 2: "constrained_2033", 3: "constrained_2028", 4: "severe_2033"}
# ordinal / count / flag ids: never scaled by horizon
UNSCALED_IDS = {"npias_capacity_label", "route_count_nonstop", "slot_or_cap_flag"}
_HORIZON_STEP = {"12m": 0, "3y": 1, "5y": 2, "10y": 3}


class FakeDataService:
    """Deterministic in-memory DataService. Construction is cheap; every call is pure."""

    def __init__(self) -> None:
        self._specs = load_registry()
        self._by_id = {s.id: s for s in self._specs}
        self._refs = {a.iata: a for a in AIRPORTS}

    # helpers
    def _spec(self, metric_id: str) -> MetricSpec:
        if metric_id not in self._by_id:
            raise KeyError(f"unknown metric id: {metric_id!r}")
        return self._by_id[metric_id]

    def _ref(self, iata: str) -> AirportRef:
        key = iata.upper()
        if key not in self._refs:
            raise KeyError(f"unknown airport: {iata!r}")
        return self._refs[key]

    def _stamped_horizon(self, spec: MetricSpec, horizon: str) -> str:
        """The horizon a value is reported AT: the requested one only if the spec declares it."""
        return horizon if horizon in spec.horizons else spec.horizons[0]

    @staticmethod
    def _is_invariant(spec: MetricSpec) -> bool:
        """Horizon-invariant: the metric declares only static and/or forecast horizons."""
        return set(spec.horizons) <= {"static", "forecast"}

    def _value(self, iata: str, metric_id: str, horizon: str) -> float | None:
        spec = self._spec(metric_id)
        if spec.tier == "C":
            return None
        # Contract: never relabel another horizon as the requested one. Horizon-invariant metrics
        # ("static"/"forecast") answer any request; everything else must declare the horizon or be None.
        if horizon not in spec.horizons and not self._is_invariant(spec):
            return None
        if spec.tier == "B":
            row = TIER_B.get(iata, {})
            return float(row[metric_id]) if metric_id in row else None
        base = BASE[iata]
        if metric_id in CAGR_IDS:
            return float(base["enpl_cagr"] * CAGR_IDS[metric_id])
        v = base.get(metric_id)  # absent => attempted but unavailable (od_share)
        if v is None:
            return None
        # scale only along a horizon the metric actually declares; invariant metrics never move
        k = _HORIZON_STEP.get(horizon, 0) if horizon in spec.horizons else 0
        if spec.unit in ("pct", "ratio") and metric_id not in UNSCALED_IDS:
            return float(v * (1 + 0.01 * k))
        return float(v)

    def _metric(self, iata: str, metric_id: str, horizon: str) -> Metric:
        spec = self._spec(metric_id)
        return Metric(id=metric_id, value=self._value(iata, metric_id, horizon), unit=spec.unit,
                      horizon=self._stamped_horizon(spec, horizon),
                      period_start="2025-05", period_end=VINT, source_id=spec.sources[0], vintage=VINT)

    # DataService
    def list_airports(self, filter: AirportFilter) -> list[AirportRef]:
        out = []
        for a in AIRPORTS:
            if filter.states and a.state not in filter.states:
                continue
            if filter.faa_regions and a.faa_region not in filter.faa_regions:
                continue
            if filter.iatas and a.iata not in filter.iatas:
                continue
            if filter.hub_sizes and a.hub_size not in filter.hub_sizes:
                continue
            if filter.name_contains and filter.name_contains.lower() not in a.name.lower():
                continue
            out.append(a)
        return out[: filter.limit]

    def get_airport(self, iata: str) -> AirportRef | None:
        return self._refs.get(iata.upper())

    def get_feature_matrix(self, airports: list[str], metric_ids: list[str], horizon: Horizon,
                           peer_group: PeerGroup = "hub_class") -> FeatureMatrix:
        refs = [self._ref(i) for i in airports]
        for m in metric_ids:
            self._spec(m)
        values = [[self._value(r.iata, m, horizon) for m in metric_ids] for r in refs]
        return FeatureMatrix(airports=refs, metric_ids=metric_ids, horizon=horizon, values=values,
                             peer_group=peer_group, vintages=self.source_vintages())

    def get_profile(self, iata: str, horizons: tuple[Horizon, ...] = ("12m", "5y")) -> AirportProfile:
        ref = self._ref(iata)
        base = BASE[ref.iata]
        metrics = {h: [self._metric(ref.iata, s.id, h) for s in self._specs if s.tier != "C"] for h in horizons}
        slot_url = ("https://www.faa.gov/about/office_org/headquarters_offices/ato/service_units/systemops/"
                    "perf_analysis/slot_administration")
        facts = [CuratedFact(iata=ref.iata, category="slot_level", text="IATA Level 2 schedule-facilitated", value=2,
                             source_url=slot_url, as_of="2026-06", expires=None)] if ref.iata in {"SFO", "LAX"} else []
        notes = ["OTP undercounts this airport (cargo/regional carriers not in OTP)"] if ref.iata == "ANC" else []
        return AirportProfile(ref=ref, metrics=metrics,
                              forecast={"taf_cagr_10y": base["taf_cagr_10y"],
                                        "npias_capacity_label": LABEL_MAP[int(base["npias_capacity_label"])]},
                              routes_summary={"nonstop_destinations": base["route_count_nonstop"]},
                              curated_facts=facts, live=self.get_live_status(ref.iata), data_quality_notes=notes,
                              vintages=self.source_vintages())

    def get_routes(self, iata: str, horizon: Horizon = "12m", top_n: int = 25,
                   international: bool | None = None) -> RouteTable:
        rows = ROUTES.get(self._ref(iata).iata, [])
        if international is not None:
            rows = [r for r in rows if r.is_international == international]
        rows = sorted(rows, key=lambda r: r.departures, reverse=True)
        return RouteTable(iata=self._ref(iata).iata, period_start="2025-05", period_end=VINT, source_id="bts_t100",
                          vintage=VINT, rows=rows[:top_n], truncated=len(rows) > top_n)

    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]:
        spec = self._spec(metric_id)
        ref = self._ref(iata)
        if self._is_invariant(spec):
            return []  # a static/forecast value has no time series
        h = self._stamped_horizon(spec, "12m")  # a 5y-only metric has a 5y series, not a 12m one
        base = self._value(ref.iata, metric_id, h)
        if base is None:  # metric unavailable here (tier C, or tier B outside the curated set) - no invented numbers
            return []
        return [Metric(id=metric_id, value=base * (1 - 0.01 * (2026 - y)), unit=spec.unit, horizon=h,
                       period_start=f"{y}-01", period_end=f"{y}-12", source_id=spec.sources[0], vintage=VINT)
                for y in range(2016, 2027)]

    def get_live_status(self, iata: str) -> LiveStatus:
        i = self._ref(iata).iata
        return LiveStatus(iata=i, delay_programs=["Ground Delay Program"] if i == "SFO" else [], ground_stop=False,
                          closure=False, latest_month={"total_passengers": 1e6}, fetched_at=FETCHED,
                          source_ids=["faa_nasstatus", "bts_socrata"])

    def describe_metrics(self) -> list[MetricSpec]:
        return list(self._specs)

    def source_vintages(self) -> list[SourceVintage]:
        ids = sorted({src for s in self._specs for src in s.sources})
        return [SourceVintage(source_id=s, description=f"fake {s}", period_start="2016-01", period_end=VINT,
                              fetched_at=FETCHED, url=None) for s in ids]


# canned data tables

# Tier-A base values at the 12m horizon; `enpl_cagr` feeds the enpl_cagr_{3y,5y,10y} family.
# `od_share` is deliberately absent everywhere - it is an attempted-but-unavailable metric (DB1B).
BASE: dict[str, dict[str, float]] = {
    "BOS": dict(enpl_cagr=0.03, taf_cagr_10y=0.021, taf_vs_actual_gap=1.02, load_factor=0.82, spill_proxy=0.06,
                seats_per_dep_trend=0.08, pax_per_capita=4.1,
                pct_arr_delay_gt15=0.22, avg_dep_delay_min=13.5, nas_delay_share=0.35, taxi_out_p80_min=24,
                ops_per_runway=68000, npias_capacity_label=4,
                carrier_hhi=1400, top_carrier_share=0.30, intl_pax_share=0.17, longhaul_dep_share=0.14,
                route_count_nonstop=140, competing_seats_100mi=6e6,
                cbsa_population=4.9e6, cbsa_pop_cagr_5y=0.004, msa_gdp_per_capita=110000, msa_gdp_cagr_5y=0.021,
                npias_dev_per_enpl=48, aip_per_enpl_10y=6, cpe_usd=18.5, nonaero_rev_per_enpl=12.9),
    "BDL": dict(enpl_cagr=0.035, taf_cagr_10y=0.018, taf_vs_actual_gap=1.05, load_factor=0.83, spill_proxy=0.07,
                seats_per_dep_trend=0.06, pax_per_capita=2.7,
                pct_arr_delay_gt15=0.19, avg_dep_delay_min=11.2, nas_delay_share=0.26, taxi_out_p80_min=17,
                ops_per_runway=32000, npias_capacity_label=0,
                carrier_hhi=2100, top_carrier_share=0.36, intl_pax_share=0.04, longhaul_dep_share=0.03,
                route_count_nonstop=32, competing_seats_100mi=8.5e6,
                cbsa_population=1.21e6, cbsa_pop_cagr_5y=0.001, msa_gdp_per_capita=92000, msa_gdp_cagr_5y=0.016,
                npias_dev_per_enpl=62, aip_per_enpl_10y=9.5, cpe_usd=11.4, nonaero_rev_per_enpl=16.5),
    "PVD": dict(enpl_cagr=0.045, taf_cagr_10y=0.019, taf_vs_actual_gap=1.03, load_factor=0.84, spill_proxy=0.08,
                seats_per_dep_trend=0.09, pax_per_capita=1.6,
                pct_arr_delay_gt15=0.20, avg_dep_delay_min=11.8, nas_delay_share=0.27, taxi_out_p80_min=16,
                ops_per_runway=30000, npias_capacity_label=0,
                carrier_hhi=2400, top_carrier_share=0.40, intl_pax_share=0.03, longhaul_dep_share=0.02,
                route_count_nonstop=26, competing_seats_100mi=9.2e6,
                cbsa_population=1.68e6, cbsa_pop_cagr_5y=0.002, msa_gdp_per_capita=71000, msa_gdp_cagr_5y=0.015,
                npias_dev_per_enpl=71, aip_per_enpl_10y=11.0, cpe_usd=8.9, nonaero_rev_per_enpl=18.4),
    "MHT": dict(enpl_cagr=0.02, taf_cagr_10y=0.015, taf_vs_actual_gap=0.97, load_factor=0.82, spill_proxy=0.07,
                seats_per_dep_trend=0.05, pax_per_capita=3.4,
                pct_arr_delay_gt15=0.18, avg_dep_delay_min=10.6, nas_delay_share=0.24, taxi_out_p80_min=15,
                ops_per_runway=27000, npias_capacity_label=0,
                carrier_hhi=2900, top_carrier_share=0.44, intl_pax_share=0.02, longhaul_dep_share=0.01,
                route_count_nonstop=18, competing_seats_100mi=8.8e6,
                cbsa_population=0.43e6, cbsa_pop_cagr_5y=0.003, msa_gdp_per_capita=78000, msa_gdp_cagr_5y=0.017,
                npias_dev_per_enpl=66, aip_per_enpl_10y=12.4, cpe_usd=8.2, nonaero_rev_per_enpl=19.1),
    "PWM": dict(enpl_cagr=0.038, taf_cagr_10y=0.016, taf_vs_actual_gap=1.01, load_factor=0.83, spill_proxy=0.075,
                seats_per_dep_trend=0.07, pax_per_capita=3.9,
                pct_arr_delay_gt15=0.17, avg_dep_delay_min=10.1, nas_delay_share=0.22, taxi_out_p80_min=14,
                ops_per_runway=24000, npias_capacity_label=0,
                carrier_hhi=2600, top_carrier_share=0.38, intl_pax_share=0.01, longhaul_dep_share=0.005,
                route_count_nonstop=22, competing_seats_100mi=2.1e6,
                cbsa_population=0.56e6, cbsa_pop_cagr_5y=0.004, msa_gdp_per_capita=74000, msa_gdp_cagr_5y=0.018,
                npias_dev_per_enpl=58, aip_per_enpl_10y=10.2, cpe_usd=8.6, nonaero_rev_per_enpl=18.9),
    "LAX": dict(enpl_cagr=0.028, taf_cagr_10y=0.019, taf_vs_actual_gap=0.99, load_factor=0.85, spill_proxy=0.05,
                seats_per_dep_trend=0.10, pax_per_capita=3.5,
                pct_arr_delay_gt15=0.21, avg_dep_delay_min=12.9, nas_delay_share=0.30, taxi_out_p80_min=22,
                ops_per_runway=66000, npias_capacity_label=3,
                carrier_hhi=1300, top_carrier_share=0.20, intl_pax_share=0.28, longhaul_dep_share=0.24,
                route_count_nonstop=165, competing_seats_100mi=1.9e7,
                cbsa_population=12.9e6, cbsa_pop_cagr_5y=-0.002, msa_gdp_per_capita=89000, msa_gdp_cagr_5y=0.019,
                npias_dev_per_enpl=41, aip_per_enpl_10y=4.2, cpe_usd=26.0, nonaero_rev_per_enpl=12.4),
    "SNA": dict(enpl_cagr=0.012, taf_cagr_10y=0.008, taf_vs_actual_gap=0.94, load_factor=0.86, spill_proxy=0.09,
                seats_per_dep_trend=0.04, pax_per_capita=3.6,
                pct_arr_delay_gt15=0.20, avg_dep_delay_min=13.9, nas_delay_share=0.28, taxi_out_p80_min=15,
                ops_per_runway=48000, npias_capacity_label=1,
                carrier_hhi=2200, top_carrier_share=0.38, intl_pax_share=0.03, longhaul_dep_share=0.02,
                route_count_nonstop=40, competing_seats_100mi=2.4e7,
                cbsa_population=3.19e6, cbsa_pop_cagr_5y=0.0, msa_gdp_per_capita=98000, msa_gdp_cagr_5y=0.020,
                npias_dev_per_enpl=22, aip_per_enpl_10y=3.1, cpe_usd=12.6, nonaero_rev_per_enpl=15.8),
    "SFO": dict(enpl_cagr=0.032, taf_cagr_10y=0.022, taf_vs_actual_gap=1.06, load_factor=0.80, spill_proxy=0.08,
                seats_per_dep_trend=0.09, pax_per_capita=5.2,
                pct_arr_delay_gt15=0.27, avg_dep_delay_min=18.0, nas_delay_share=0.45, taxi_out_p80_min=26,
                ops_per_runway=62000, npias_capacity_label=4,
                carrier_hhi=2600, top_carrier_share=0.46, intl_pax_share=0.32, longhaul_dep_share=0.26,
                route_count_nonstop=130, competing_seats_100mi=1.5e7,
                cbsa_population=4.6e6, cbsa_pop_cagr_5y=0.001, msa_gdp_per_capita=155000, msa_gdp_cagr_5y=0.028,
                npias_dev_per_enpl=55, aip_per_enpl_10y=5.1, cpe_usd=24.8, nonaero_rev_per_enpl=13.6),
    "BUR": dict(enpl_cagr=0.02, taf_cagr_10y=0.012, taf_vs_actual_gap=0.98, load_factor=0.84, spill_proxy=0.06,
                seats_per_dep_trend=0.03, pax_per_capita=0.5,
                pct_arr_delay_gt15=0.19, avg_dep_delay_min=11.9, nas_delay_share=0.24, taxi_out_p80_min=13,
                ops_per_runway=38000, npias_capacity_label=0,
                carrier_hhi=3400, top_carrier_share=0.52, intl_pax_share=0.005, longhaul_dep_share=0.01,
                route_count_nonstop=24, competing_seats_100mi=3.1e7,
                cbsa_population=12.9e6, cbsa_pop_cagr_5y=-0.002, msa_gdp_per_capita=89000, msa_gdp_cagr_5y=0.019,
                npias_dev_per_enpl=26, aip_per_enpl_10y=4.6, cpe_usd=10.9, nonaero_rev_per_enpl=16.9),
    "ANC": dict(enpl_cagr=0.015, taf_cagr_10y=0.011, taf_vs_actual_gap=1.0, load_factor=0.78, spill_proxy=0.11,
                seats_per_dep_trend=0.02, pax_per_capita=6.4,
                pct_arr_delay_gt15=0.16, avg_dep_delay_min=9.8, nas_delay_share=0.18, taxi_out_p80_min=12,
                ops_per_runway=44000, npias_capacity_label=0,
                carrier_hhi=3100, top_carrier_share=0.44, intl_pax_share=0.05, longhaul_dep_share=0.30,
                route_count_nonstop=30, competing_seats_100mi=5e4,
                cbsa_population=0.4e6, cbsa_pop_cagr_5y=-0.001, msa_gdp_per_capita=82000, msa_gdp_cagr_5y=0.012,
                npias_dev_per_enpl=95, aip_per_enpl_10y=24.0, cpe_usd=9.9, nonaero_rev_per_enpl=15.2),
    "JFK": dict(enpl_cagr=0.036, taf_cagr_10y=0.020, taf_vs_actual_gap=1.04, load_factor=0.84, spill_proxy=0.07,
                seats_per_dep_trend=0.11, pax_per_capita=1.8,
                pct_arr_delay_gt15=0.25, avg_dep_delay_min=16.4, nas_delay_share=0.42, taxi_out_p80_min=30,
                ops_per_runway=71000, npias_capacity_label=4,
                carrier_hhi=1900, top_carrier_share=0.33, intl_pax_share=0.55, longhaul_dep_share=0.41,
                route_count_nonstop=145, competing_seats_100mi=3.6e7,
                cbsa_population=19.5e6, cbsa_pop_cagr_5y=0.0, msa_gdp_per_capita=105000, msa_gdp_cagr_5y=0.022,
                npias_dev_per_enpl=44, aip_per_enpl_10y=3.8, cpe_usd=36.0, nonaero_rev_per_enpl=13.9),
    "ATL": dict(enpl_cagr=0.024, taf_cagr_10y=0.017, taf_vs_actual_gap=1.01, load_factor=0.86, spill_proxy=0.04,
                seats_per_dep_trend=0.06, pax_per_capita=8.4,
                pct_arr_delay_gt15=0.20, avg_dep_delay_min=11.6, nas_delay_share=0.29, taxi_out_p80_min=20,
                ops_per_runway=105000, npias_capacity_label=2,
                carrier_hhi=5500, top_carrier_share=0.74, intl_pax_share=0.11, longhaul_dep_share=0.09,
                route_count_nonstop=155, competing_seats_100mi=1.2e6,
                cbsa_population=6.3e6, cbsa_pop_cagr_5y=0.011, msa_gdp_per_capita=79000, msa_gdp_cagr_5y=0.024,
                npias_dev_per_enpl=38, aip_per_enpl_10y=3.4, cpe_usd=3.9, nonaero_rev_per_enpl=12.6),
    "DEN": dict(enpl_cagr=0.05, taf_cagr_10y=0.026, taf_vs_actual_gap=1.08, load_factor=0.85, spill_proxy=0.05,
                seats_per_dep_trend=0.07, pax_per_capita=12.6,
                pct_arr_delay_gt15=0.22, avg_dep_delay_min=13.2, nas_delay_share=0.26, taxi_out_p80_min=19,
                ops_per_runway=55000, npias_capacity_label=1,
                carrier_hhi=3600, top_carrier_share=0.51, intl_pax_share=0.05, longhaul_dep_share=0.06,
                route_count_nonstop=175, competing_seats_100mi=0.8e6,
                cbsa_population=3.0e6, cbsa_pop_cagr_5y=0.008, msa_gdp_per_capita=92000, msa_gdp_cagr_5y=0.025,
                npias_dev_per_enpl=72, aip_per_enpl_10y=5.4, cpe_usd=14.2, nonaero_rev_per_enpl=13.8),
}

TIER_B: dict[str, dict[str, float]] = {  # curated majors only; every other airport is None on tier B
    "BOS": dict(peak_hour_ops_ratio=0.9, pax_per_gate=420000, deps_per_gate_day=5.2, imc_capacity_ratio=0.75,
                slot_or_cap_flag=0),
    "LAX": dict(peak_hour_ops_ratio=0.95, pax_per_gate=520000, deps_per_gate_day=5.6, imc_capacity_ratio=0.80,
                slot_or_cap_flag=1),
    "SFO": dict(peak_hour_ops_ratio=1.0, pax_per_gate=470000, deps_per_gate_day=5.4, imc_capacity_ratio=0.70,
                slot_or_cap_flag=1),
    "JFK": dict(peak_hour_ops_ratio=1.0, pax_per_gate=480000, deps_per_gate_day=5.0, imc_capacity_ratio=0.85,
                slot_or_cap_flag=1),
    "SNA": dict(peak_hour_ops_ratio=0.85, pax_per_gate=560000, deps_per_gate_day=6.1, imc_capacity_ratio=0.85,
                slot_or_cap_flag=1),
}


def _r(dest: str, name: str, mi: float, deps: int, seats: int, pax: int, freight: float, intl: bool) -> RouteRow:
    return RouteRow(dest=dest, dest_name=name, distance_mi=mi, departures=deps, seats=seats, passengers=pax,
                    freight_lb=freight, is_international=intl)


ROUTES: dict[str, list[RouteRow]] = {
    "BOS": [_r("DCA", "Washington National", 399, 7200, 780000, 640000, 3e6, False),
            _r("LGA", "New York LaGuardia", 185, 6100, 620000, 500000, 2e6, False),
            _r("ORD", "Chicago", 867, 4300, 620000, 520000, 5e6, False),
            _r("LAX", "Los Angeles", 2611, 2600, 480000, 410000, 8e6, False),
            _r("LHR", "London", 3265, 2100, 620000, 540000, 3e7, True)],
    "BDL": [_r("BWI", "Baltimore", 283, 2400, 290000, 240000, 4e5, False),
            _r("ORD", "Chicago", 783, 1900, 200000, 165000, 6e5, False),
            _r("ATL", "Atlanta", 859, 2200, 240000, 200000, 7e5, False),
            _r("MCO", "Orlando", 1050, 1700, 250000, 215000, 2e5, False),
            _r("DTW", "Detroit", 553, 1500, 130000, 105000, 3e5, False)],
    "PVD": [_r("BWI", "Baltimore", 328, 2100, 260000, 220000, 3e5, False),
            _r("MCO", "Orlando", 1073, 1600, 240000, 205000, 1e5, False),
            _r("ATL", "Atlanta", 903, 1500, 165000, 138000, 4e5, False),
            _r("CLT", "Charlotte", 683, 1300, 105000, 86000, 2e5, False)],
    "MHT": [_r("BWI", "Baltimore", 377, 1500, 185000, 152000, 2e5, False),
            _r("MCO", "Orlando", 1142, 1100, 165000, 140000, 8e4, False),
            _r("ORD", "Chicago", 843, 900, 70000, 57000, 2e5, False),
            _r("PHL", "Philadelphia", 288, 800, 55000, 44000, 1e5, False)],
    "PWM": [_r("DCA", "Washington National", 468, 1400, 105000, 87000, 2e5, False),
            _r("PHL", "Philadelphia", 359, 1200, 88000, 71000, 1e5, False),
            _r("LGA", "New York LaGuardia", 273, 1100, 78000, 62000, 9e4, False),
            _r("MCO", "Orlando", 1245, 700, 105000, 92000, 5e4, False)],
    "LAX": [_r("SFO", "San Francisco", 337, 9800, 1250000, 1020000, 1e7, False),
            _r("LAS", "Las Vegas", 236, 6400, 830000, 690000, 4e6, False),
            _r("JFK", "New York Kennedy", 2475, 6000, 1100000, 950000, 2e7, False),
            _r("ORD", "Chicago", 1745, 5200, 780000, 660000, 1.5e7, False),
            _r("LHR", "London", 5456, 1800, 560000, 490000, 5e7, True),
            _r("NRT", "Tokyo Narita", 5451, 1500, 480000, 410000, 6e7, True)],
    "SNA": [_r("SFO", "San Francisco", 372, 3400, 320000, 265000, 6e5, False),
            _r("PHX", "Phoenix", 338, 3100, 380000, 320000, 5e5, False),
            _r("DEN", "Denver", 846, 2900, 400000, 345000, 8e5, False),
            _r("SJC", "San Jose", 342, 2400, 220000, 180000, 3e5, False),
            _r("SEA", "Seattle", 978, 2200, 300000, 258000, 7e5, False)],
    "SFO": [_r("LAX", "Los Angeles", 337, 9600, 1230000, 990000, 1e7, False),
            _r("SEA", "Seattle", 679, 4400, 560000, 455000, 5e6, False),
            _r("JFK", "New York Kennedy", 2586, 3900, 720000, 610000, 1.8e7, False),
            _r("LHR", "London", 5367, 1500, 470000, 410000, 4e7, True),
            _r("HKG", "Hong Kong", 6927, 1100, 380000, 330000, 8e7, True)],
    "BUR": [_r("LAS", "Las Vegas", 223, 2600, 300000, 245000, 2e5, False),
            _r("PHX", "Phoenix", 369, 2300, 270000, 225000, 2e5, False),
            _r("OAK", "Oakland", 325, 2000, 230000, 185000, 1e5, False),
            _r("SEA", "Seattle", 937, 1400, 190000, 160000, 3e5, False)],
    "ANC": [_r("SEA", "Seattle", 1449, 3000, 450000, 380000, 1e6, False),
            _r("FAI", "Fairbanks", 261, 2500, 250000, 200000, 2e6, False),
            _r("HKG", "Hong Kong", 5060, 900, 0, 0, 9e7, True),
            _r("ICN", "Seoul", 3760, 800, 0, 0, 8e7, True),
            _r("ORD", "Chicago", 2846, 600, 100000, 85000, 5e5, False),
            _r("MSP", "Minneapolis", 2513, 400, 70000, 60000, 1e5, False)],
    "JFK": [_r("LAX", "Los Angeles", 2475, 6000, 1100000, 950000, 2e7, False),
            _r("LHR", "London", 3451, 4000, 1200000, 1050000, 5e7, True),
            _r("CDG", "Paris", 3635, 2500, 800000, 700000, 3e7, True)],
    "ATL": [_r("MCO", "Orlando", 404, 8600, 1150000, 990000, 3e6, False),
            _r("LGA", "New York LaGuardia", 762, 6900, 780000, 660000, 4e6, False),
            _r("ORD", "Chicago", 606, 6200, 720000, 615000, 6e6, False),
            _r("DFW", "Dallas-Fort Worth", 731, 5400, 640000, 545000, 5e6, False),
            _r("CUN", "Cancun", 1153, 1600, 260000, 230000, 1e6, True)],
    "DEN": [_r("LAX", "Los Angeles", 862, 6300, 830000, 700000, 5e6, False),
            _r("ORD", "Chicago", 888, 5800, 760000, 645000, 6e6, False),
            _r("PHX", "Phoenix", 602, 5100, 690000, 585000, 3e6, False),
            _r("DFW", "Dallas-Fort Worth", 641, 4600, 560000, 470000, 4e6, False),
            _r("MEX", "Mexico City", 1465, 900, 150000, 130000, 2e6, True)],
}
