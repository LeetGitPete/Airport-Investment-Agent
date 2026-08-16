"""`DuckDBDataService` — the `DataService` Protocol implemented over the committed snapshot.

Read-only: `duckdb.connect(path, read_only=True)`. Live status (`faa_nasstatus`) is queried
at answer time with a 3s timeout, falling back to a snapshot-derived `LiveStatus` on any
failure or when `live=False` (design 03 "acceptable degradation" — data freshness, not
reasoning).

**Horizon rule (restated from the frozen `DataService.get_feature_matrix` docstring):** a
metric's value is looked up at the *requested* horizon only if `MetricSpec.horizons`
declares it; horizon-invariant metrics (`horizons <= {"static", "forecast"}`) answer any
request at their own single declared horizon. A metric never borrows another horizon's real
value to answer an undeclared one — undeclared means `None`, always (see
`_value`/`_lookup_horizon`). Multi-year semantics (from `derived/common.py`, restated
here): **CAGR-type metrics are k-year growth; level metrics at
horizon k are computed over the trailing k-year window** ending at the metric's own
underlying source's latest available period (12m = trailing 12 months). Different sources
(Socrata, OTP, T-100) publish on different, independent cadences (see
`derived/p2_congestion.py`'s `_otp_latest_period`), so "the trailing k years" ends at
different real calendar months for different metrics; every `Metric`/row still carries its
own `period_start`/`period_end` so this is never hidden.

Memoization (scoped narrowly — no report caching): the metric registry
(`load_registry()`) and the `list_airports` commercial-airport universe are each computed
once per process and reused; every other method reads the snapshot fresh.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from airport_agent.contracts.models import (
    AirportFilter,
    AirportProfile,
    AirportRef,
    CuratedFact,
    FeatureMatrix,
    Horizon,
    LiveStatus,
    Metric,
    MetricSpec,
    PeerGroup,
    QualityFlag,
    RouteRow,
    RouteTable,
    SourceVintage,
)
from airport_agent.contracts.registry import load_registry
from airport_agent.data import quality
from airport_agent.data.adapters.faa_nasstatus import FaaNasStatusLiveAdapter
from airport_agent.data.commercial import COMMERCIAL_EXISTS_SQL
from airport_agent.data.derived import CURRENT_REF_YEAR, common
from airport_agent.data.paths import default_snapshot_path

#: Horizons a metric answers at "its own" declared horizon regardless of what was requested.
_INVARIANT_HORIZONS = {"static", "forecast"}

#: `get_live_status`/`get_profile` snapshot fallback (live adapter unavailable or `live=False`).
_SNAPSHOT_LIVE_SOURCE_IDS = ["bts_socrata"]

_LIVE_TIMEOUT_SECONDS = 3.0

_AIRPORT_SELECT_COLUMNS = "iata, icao, faa_locid, name, city, state, faa_region, hub_size, lat, lon"


def _is_invariant(spec: MetricSpec) -> bool:
    return set(spec.horizons) <= _INVARIANT_HORIZONS


def _lookup_horizon(spec: MetricSpec, horizon: str) -> str | None:
    """The horizon to read `airport_metrics` at for `horizon`, or `None` if undeclared.

    Invariant metrics always answer at their own single horizon; everything else must
    declare `horizon` exactly (never borrows a different horizon's value)."""
    if _is_invariant(spec):
        return spec.horizons[0]
    return horizon if horizon in spec.horizons else None


def _stamped_horizon(spec: MetricSpec, horizon: str) -> str:
    """The horizon LABEL a `Metric` is reported at: `horizon` if declared, else the metric's
    first declared horizon (mirrors `tests/fakes.py::FakeDataService._stamped_horizon` —
    used only for the `Metric.horizon` field, never to fetch a value from elsewhere)."""
    return horizon if horizon in spec.horizons else spec.horizons[0]


def _row_to_airport_ref(row: tuple) -> AirportRef:
    iata, icao, faa_locid, name, city, state, faa_region, hub_size, lat, lon = row
    return AirportRef(
        iata=iata, icao=icao, faa_locid=faa_locid, name=name, city=city, state=state,
        faa_region=faa_region or "", hub_size=hub_size or "nonhub", lat=lat, lon=lon,
    )


class DuckDBDataService:
    """`DataService` over a read-only DuckDB snapshot (`data/snapshot/airports.duckdb`)."""

    def __init__(self, path: Path | None = None, live: bool = True) -> None:
        self.path = Path(path) if path is not None else default_snapshot_path()
        self.con = duckdb.connect(str(self.path), read_only=True)
        self.live = live
        self._specs: list[MetricSpec] = load_registry()
        self._by_id: dict[str, MetricSpec] = {s.id: s for s in self._specs}
        self._universe: list[AirportRef] | None = None
        self._nasstatus = FaaNasStatusLiveAdapter()

    # registry helpers
    def _spec(self, metric_id: str) -> MetricSpec:
        if metric_id not in self._by_id:
            raise KeyError(f"unknown metric id: {metric_id!r}")
        return self._by_id[metric_id]

    # airport lookups
    def _airport_universe(self) -> list[AirportRef]:
        """Every commercial airport (see `data/commercial.py`), ordered by latest annual
        enplanements desc then iata — computed once per process."""
        if self._universe is None:
            rows = self.con.execute(
                f"""
                SELECT {_AIRPORT_SELECT_COLUMNS}
                FROM airports a
                WHERE {COMMERCIAL_EXISTS_SQL}
                ORDER BY COALESCE(
                    (SELECT value FROM airport_year y WHERE y.iata = a.iata AND y.measure = 'enplanements'
                     QUALIFY ROW_NUMBER() OVER (PARTITION BY y.iata ORDER BY y.year DESC) = 1), 0
                ) DESC, a.iata ASC
                """  # noqa: S608
            ).fetchall()
            self._universe = [_row_to_airport_ref(r) for r in rows]
        return self._universe

    def list_airports(self, filter: AirportFilter) -> list[AirportRef]:  # parameter name matches the frozen Protocol
        out = []
        for a in self._airport_universe():
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
            if filter.cbsa_codes:
                row = self.con.execute("SELECT cbsa_code FROM airports WHERE iata = ?", [a.iata]).fetchone()
                if not row or row[0] not in filter.cbsa_codes:
                    continue
            out.append(a)
        return out[: filter.limit]

    def get_airport(self, iata: str) -> AirportRef | None:
        row = self.con.execute(
            f"SELECT {_AIRPORT_SELECT_COLUMNS} FROM airports WHERE iata = ?", [iata.upper()]  # noqa: S608
        ).fetchone()
        return _row_to_airport_ref(row) if row else None

    def _ref_or_raise(self, iata: str) -> AirportRef:
        ref = self.get_airport(iata)
        if ref is None:
            raise KeyError(f"unknown airport: {iata!r}")
        return ref

    # metric value lookups
    def _value(self, iata: str, metric_id: str, horizon: str) -> float | None:
        spec = self._spec(metric_id)
        if spec.tier == "C":
            return None
        lookup_horizon = _lookup_horizon(spec, horizon)
        if lookup_horizon is None:
            return None
        row = self.con.execute(
            "SELECT value FROM airport_metrics WHERE iata = ? AND metric_id = ? AND horizon = ? AND ref_year = ?",
            [iata, metric_id, lookup_horizon, CURRENT_REF_YEAR],
        ).fetchone()
        return row[0] if row else None

    def _metric_row(self, iata: str, metric_id: str, horizon: str) -> tuple | None:
        spec = self._spec(metric_id)
        lookup_horizon = _lookup_horizon(spec, horizon)
        if lookup_horizon is None:
            return None
        return self.con.execute(
            "SELECT value, period_start, period_end, source_id, vintage, quality_json "
            "FROM airport_metrics WHERE iata = ? AND metric_id = ? AND horizon = ? AND ref_year = ?",
            [iata, metric_id, lookup_horizon, CURRENT_REF_YEAR],
        ).fetchone()

    def _metric(self, iata: str, metric_id: str, horizon: str) -> Metric:
        spec = self._spec(metric_id)
        row = self._metric_row(iata, metric_id, horizon) if spec.tier != "C" else None
        stamped = _stamped_horizon(spec, horizon)
        if row is None:
            return Metric(
                id=metric_id, value=None, unit=spec.unit, horizon=stamped, period_start=None, period_end=None,
                source_id=spec.sources[0], vintage="n/a", quality=[],
            )
        value, period_start, period_end, source_id, vintage, quality_json = row
        flags = [{"code": f["code"], "message": f["message"]} for f in json.loads(quality_json)]
        return Metric(
            id=metric_id, value=value, unit=spec.unit, horizon=stamped, period_start=period_start,
            period_end=period_end, source_id=source_id, vintage=vintage,
            quality=[QualityFlag(**f) for f in flags],
        )

    # DataService
    def get_feature_matrix(
        self, airports: list[str], metric_ids: list[str], horizon: Horizon, peer_group: PeerGroup = "hub_class"
    ) -> FeatureMatrix:
        refs = [self._ref_or_raise(i) for i in airports]
        for m in metric_ids:
            self._spec(m)  # KeyError on unknown metric id
        values = [[self._value(r.iata, m, horizon) for m in metric_ids] for r in refs]
        return FeatureMatrix(
            airports=refs, metric_ids=metric_ids, horizon=horizon, values=values,
            peer_group=peer_group, vintages=self.source_vintages(),
        )

    def get_profile(self, iata: str, horizons: tuple[Horizon, ...] = ("12m", "5y")) -> AirportProfile:
        ref = self._ref_or_raise(iata)
        metrics = {h: [self._metric(ref.iata, s.id, h) for s in self._specs if s.tier != "C"] for h in horizons}
        forecast = self._forecast(ref)
        routes_summary = self._routes_summary(ref.iata)
        curated_facts = self._curated_facts(ref.iata)
        return AirportProfile(
            ref=ref, metrics=metrics, forecast=forecast, routes_summary=routes_summary,
            curated_facts=curated_facts, live=self.get_live_status(ref.iata),
            data_quality_notes=quality.data_quality_notes(self.con, ref.iata), vintages=self.source_vintages(),
        )

    def _forecast(self, ref: AirportRef) -> dict[str, float | str | None]:
        taf_cagr = self._value(ref.iata, "taf_cagr_10y", "forecast")
        row = self.con.execute(
            "SELECT n.capacity_label_text FROM npias n WHERE n.faa_locid = ?", [ref.faa_locid]
        ).fetchone()
        label_text = row[0] if row else None
        base_row = self.con.execute("SELECT MIN(year) FROM taf_forecast").fetchone()
        base_year = base_row[0] if base_row else None
        return {"taf_cagr_10y": taf_cagr, "npias_capacity_label": label_text, "taf_base_year": base_year}

    def _routes_summary(self, iata: str) -> dict[str, float | str | None]:
        latest = self.con.execute("SELECT MAX(period) FROM routes_month").fetchone()
        latest_period = latest[0] if latest else None
        if latest_period is None:
            return {
                "nonstop_destinations": None, "top_dest": None,
                "intl_share_of_departures": None, "freight_share_long_haul": None,
            }
        start, end = common.window_months("12m", latest_period)
        df = self.con.execute(
            """
            SELECT dest, SUM(departures) AS deps, SUM(freight_lb) AS freight, MAX(distance_mi) AS distance,
                   BOOL_OR(is_international) AS is_intl
            FROM routes_month WHERE iata = ? AND period BETWEEN ? AND ?
            GROUP BY dest
            """,
            [iata, start, end],
        ).df()
        if df.empty:
            return {
                "nonstop_destinations": 0, "top_dest": None,
                "intl_share_of_departures": None, "freight_share_long_haul": None,
            }
        top_dest = df.loc[df["deps"].idxmax(), "dest"]
        total_deps = df["deps"].sum()
        intl_deps = df.loc[df["is_intl"], "deps"].sum()
        total_freight = df["freight"].sum()
        long_freight = df.loc[df["distance"] >= common.LONG_HAUL_MI, "freight"].sum()
        return {
            "nonstop_destinations": int(df["dest"].nunique()),
            "top_dest": top_dest,
            "intl_share_of_departures": float(intl_deps / total_deps) if total_deps else None,
            "freight_share_long_haul": float(long_freight / total_freight) if total_freight else None,
        }

    def _curated_facts(self, iata: str) -> list[CuratedFact]:
        rows = self.con.execute(
            "SELECT category, text, value, source_url, as_of, expires FROM curated_facts WHERE iata = ?", [iata]
        ).fetchall()
        return [
            CuratedFact(iata=iata, category=c, text=t, value=v, source_url=u, as_of=a, expires=e)
            for c, t, v, u, a, e in rows
        ]

    def get_routes(
        self, iata: str, horizon: Horizon = "12m", top_n: int = 25, international: bool | None = None
    ) -> RouteTable:
        ref = self._ref_or_raise(iata)
        latest = self.con.execute("SELECT MAX(period) FROM routes_month").fetchone()
        latest_period = latest[0] if latest else None
        if latest_period is None:
            return RouteTable(
                iata=ref.iata, period_start="n/a", period_end="n/a", source_id="bts_t100", vintage="n/a",
                rows=[], truncated=False,
            )
        start, end = common.window_months(horizon, latest_period)
        df = self.con.execute(
            """
            SELECT dest, ANY_VALUE(dest_name) AS dest_name, AVG(distance_mi) AS distance_mi,
                   SUM(departures) AS departures, SUM(seats) AS seats, SUM(passengers) AS passengers,
                   SUM(freight_lb) AS freight_lb, BOOL_OR(is_international) AS is_international
            FROM routes_month
            WHERE iata = ? AND period BETWEEN ? AND ?
              AND (? IS NULL OR is_international = ?)
            GROUP BY dest
            -- `dest` breaks the tie so the order is TOTAL: the caller slices to top_n, which makes
            -- ordering decide MEMBERSHIP, not just position. Without it, which routes an airport
            -- shows would come from DuckDB's execution order (252 airports have a tie straddling
            -- the default top_n=10). Matches `_airport_universe` and `Scorer.score`.
            ORDER BY departures DESC, dest ASC
            """,
            [iata, start, end, international, international],
        ).df()
        rows = [
            RouteRow(
                dest=r.dest, dest_name=r.dest_name, distance_mi=float(r.distance_mi or 0.0),
                departures=int(r.departures or 0), seats=int(r.seats or 0), passengers=int(r.passengers or 0),
                freight_lb=float(r.freight_lb or 0.0), is_international=bool(r.is_international),
            )
            for r in df.itertuples()
        ]
        truncated = len(rows) > top_n
        return RouteTable(
            iata=ref.iata, period_start=start, period_end=end, source_id="bts_t100", vintage=end,
            rows=rows[:top_n], truncated=truncated,
        )

    def get_metric_series(self, iata: str, metric_id: str) -> list[Metric]:
        ref = self._ref_or_raise(iata)
        spec = self._spec(metric_id)
        if spec.tier == "C" or _is_invariant(spec):
            return []
        horizon = _stamped_horizon(spec, "12m")
        rows = self.con.execute(
            "SELECT ref_year, value, period_start, period_end, source_id, vintage, quality_json "
            "FROM airport_metrics WHERE iata = ? AND metric_id = ? AND horizon = ? AND ref_year != ? "
            "ORDER BY ref_year",
            [ref.iata, metric_id, horizon, CURRENT_REF_YEAR],
        ).fetchall()
        return [
            Metric(
                id=metric_id, value=value, unit=spec.unit, horizon=horizon, period_start=period_start,
                period_end=period_end, source_id=source_id, vintage=vintage,
                quality=[QualityFlag(**f) for f in json.loads(quality_json)],
            )
            for _, value, period_start, period_end, source_id, vintage, quality_json in rows
        ]

    def get_live_status(self, iata: str) -> LiveStatus:
        ref = self._ref_or_raise(iata)
        status: dict | None = None
        if self.live:
            status = self._nasstatus.fetch_status(timeout=_LIVE_TIMEOUT_SECONDS)
        if status is not None and ref.iata in status:
            entry = status[ref.iata]
            latest_month = self._latest_socrata_totals(ref.iata)
            return LiveStatus(
                iata=ref.iata, delay_programs=entry["delay_programs"], ground_stop=entry["ground_stop"],
                closure=entry["closure"], latest_month=latest_month,
                fetched_at=self._nasstatus.vintage().fetched_at or "unknown",
                source_ids=["faa_nasstatus", *_SNAPSHOT_LIVE_SOURCE_IDS],
            )
        # Live feed unavailable, `live=False`, or the feed has nothing to report for this
        # airport: fall back to the snapshot (design 03 — acceptable degradation).
        latest_month = self._latest_socrata_totals(ref.iata)
        return LiveStatus(
            iata=ref.iata, delay_programs=[], ground_stop=False, closure=False, latest_month=latest_month,
            fetched_at=self._latest_socrata_period(ref.iata) or "unknown", source_ids=_SNAPSHOT_LIVE_SOURCE_IDS,
        )

    def _latest_socrata_period(self, iata: str) -> str | None:
        row = self.con.execute(
            "SELECT MAX(period) FROM airport_month WHERE iata = ? AND measure = 'total_passengers'", [iata]
        ).fetchone()
        return row[0] if row else None

    def _latest_socrata_totals(self, iata: str) -> dict[str, float] | None:
        period = self._latest_socrata_period(iata)
        if period is None:
            return None
        rows = self.con.execute(
            "SELECT measure, value FROM airport_month WHERE iata = ? AND period = ?", [iata, period]
        ).fetchall()
        return {measure: value for measure, value in rows} or None

    def describe_metrics(self) -> list[MetricSpec]:
        return list(self._specs)

    def source_vintages(self) -> list[SourceVintage]:
        rows = self.con.execute(
            "SELECT source_id, description, period_start, period_end, fetched_at, url FROM source_vintage"
        ).fetchall()
        return [
            SourceVintage(source_id=r[0], description=r[1], period_start=r[2], period_end=r[3], fetched_at=r[4], url=r[5])
            for r in rows
        ]
