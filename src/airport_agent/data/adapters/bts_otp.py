"""BTS On-Time Performance adapter — delay measures, taxi-out histogram, peak hourly ops.

Source: `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_
1987_present_{YYYY}_{M}.zip` (one stable, no-auth URL per month; see
docs/research/2026-08-15-us-aviation-data-sources.md §1). This is the row-level
flight file the congestion metrics (`pct_arr_delay_gt15`, `avg_dep_delay_min`,
`taxi_out_p80_min`, `peak_hour_ops_ratio`) run on. Everything is aggregated to
airport-month at ingest — raw rows are never stored.

Verified 2026-08-16 against the real June 2026 file:

* Every column name in the research note/plan is exact: `Year, Month, DayofMonth,
  Origin, Dest, CRSDepTime, CRSArrTime, DepDelayMinutes, ArrDelayMinutes,
  ArrDel15, TaxiOut, Cancelled, Diverted, CarrierDelay, WeatherDelay, NASDelay,
  SecurityDelay, LateAircraftDelay` (`DayofMonth` added here — not in the plan's
  usecols list, but required to build the day×hour grid for `otp_peak`).
* `Cancelled`/`Diverted`/`ArrDel15` are `0.0`/`1.0` floats, not booleans.
* `CRSDepTime`/`CRSArrTime` are `HHMM` integers, range verified `1..2359` (no
  `2400` sentinel seen in this file) — hour = `time // 100`.
* `TaxiOut` and the five delay-cause columns are `NaN` for cancelled flights
  (verified: 10,019 cancelled rows vs 9,982 missing `TaxiOut` — the ~37-row gap
  is diverted-but-not-cancelled flights that never took off); the delay-cause
  columns are also `NaN` for on-time/early flights (BTS only breaks out cause
  minutes for arrivals delayed 15+ minutes).
* `DepDelayMinutes` is **not** always `NaN` on a cancelled flight (verified: a
  handful of real rows record a pushback delay before the eventual
  cancellation) — every Origin-based sum (`dep_delay_min_sum` and the five
  delay-cause minutes) is therefore computed on the `Cancelled == 0` subset
  explicitly, not by relying on `pandas.sum()`'s NaN-skipping, so it always
  divides cleanly by `dep_count` (same subset).
* One month, all US airports: ~608k rows, ~275 MB CSV (~30 MB zipped). A full
  month is read, aggregated, and discarded per `normalize` call — nothing
  row-level is written to the store.
* Diverted flights are **not** specially excluded from `dep_count`/`arrivals`
  (the plan's measure list has no diverted-specific rule): a diverted flight
  that departed counts as a departure; if it has an `ArrDel15` value at its
  scheduled destination that value is counted too. This is a known BTS
  data nuance, not engineered around here.

Measures written to `airport_month` (Origin-based unless noted): `dep_count`,
`dep_delay_min_sum`, `cancelled_dep`, `carrier_delay_min`, `weather_delay_min`,
`nas_delay_min`, `security_delay_min`, `late_aircraft_delay_min`; (Dest-based)
`arrivals`, `arr_late15`. `otp_taxi_hist(iata, period, minute_bucket, n)`:
`minute_bucket = min(int(TaxiOut), 180)`, non-cancelled flights only (`TaxiOut`
is already `NaN` when cancelled). `otp_peak(iata, period, p95_hourly_ops,
max_hourly_ops)`: hourly ops = departures scheduled that (day, hour) at `iata`
plus arrivals scheduled that (day, hour) at `iata` (non-cancelled only),
zero-filled over every (day, hour) covered by the file (so quiet overnight
hours count as zero, not "missing") — `p95`/`max` taken over that grid per
airport-month.

**Trailing window:** `otp_months` in `config/sources.yaml` is **12**, so OTP
covers only the trailing 12 months and the `3y`/`5y` delay horizons
(`pct_arr_delay_gt15`, `avg_dep_delay_min`) are `None` beyond `12m` rather than
dishonestly labelled. This keeps the OTP download to ~360 MB raw instead of ~1.1 GB.
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

URL_TEMPLATE = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

#: Source CSV columns this adapter reads (of the 110 the full file has).
SOURCE_COLUMNS: tuple[str, ...] = (
    "Year",
    "Month",
    "DayofMonth",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSArrTime",
    "DepDelayMinutes",
    "ArrDelayMinutes",
    "ArrDel15",
    "TaxiOut",
    "Cancelled",
    "Diverted",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
)

#: `airport_month` measures this adapter writes (Origin-based unless noted).
DEP_MEASURES: tuple[str, ...] = (
    "dep_count",
    "dep_delay_min_sum",
    "cancelled_dep",
    "carrier_delay_min",
    "weather_delay_min",
    "nas_delay_min",
    "security_delay_min",
    "late_aircraft_delay_min",
)
#: Dest-based measures.
ARR_MEASURES: tuple[str, ...] = ("arrivals", "arr_late15")

AIRPORT_MONTH_COLUMNS: tuple[str, ...] = ("iata", "period", "measure", "value", "source_id", "vintage")
TAXI_HIST_COLUMNS: tuple[str, ...] = ("iata", "period", "minute_bucket", "n", "source_id", "vintage")
OTP_PEAK_COLUMNS: tuple[str, ...] = ("iata", "period", "p95_hourly_ops", "max_hourly_ops", "source_id", "vintage")

#: TaxiOut minutes above this are folded into the top bucket.
MAX_TAXI_BUCKET = 180

HOURS_IN_DAY = tuple(range(24))


def _url(period: Period) -> str:
    if period.month is None:
        raise ValueError("bts_otp requires a specific month (Period(year, month))")
    return URL_TEMPLATE.format(year=period.year, month=period.month)


def _extract_data_csv(zip_path: Path, dest: Path) -> Path:
    """Extract the one data CSV from the zip (`readme.html` is documentation, skipped)."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected exactly one data CSV in {zip_path.name}, found {names}")
        member = names[0]
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
    stamp = calendar.timegm((*info.date_time, 0, 0, -1))
    os.utime(dest, (stamp, stamp))
    return dest


def _hour_of(series: pd.Series) -> pd.Series:
    """`HHMM` int -> hour 0-23 (verified range 1..2359 in the real file, no 2400 sentinel)."""
    numeric = pd.to_numeric(series, errors="coerce")
    return ((numeric // 100) % 24).astype("Int64")


@register
class BtsOtpAdapter:
    """Fetch/normalize BTS On-Time Performance into `airport_month`, `otp_taxi_hist`, `otp_peak`."""

    id: str = "bts_otp"
    kind: Literal["bulk", "live"] = "bulk"

    def __init__(self) -> None:
        # Provisional only: `fetch`/`normalize` replace these with the raw file's own date
        # (see `file_vintage`), so provenance describes the data, not this process.
        now = datetime.now(UTC)
        self._vintage: str = now.date().isoformat()
        self._fetched_at: str = now.isoformat()
        self._period_start: str | None = None
        self._period_end: str | None = None

    # -- fetch ---------------------------------------------------------------
    def fetch(self, period: Period | None, cache_dir: Path) -> list[Path]:
        """Download one month's PREZIP zip (cached) and extract its data CSV.

        `period` is required (`Period(year, month)`) — there is one file per month, no
        "everything" option, like `bts_t100`.
        """
        if period is None:
            raise ValueError("bts_otp requires an explicit period (year and month)")
        url = _url(period)
        zip_path = download(url, cache_dir, filename=f"bts_otp_{period.label()}.zip")
        csv_path = _extract_data_csv(zip_path, Path(cache_dir) / f"bts_otp_{period.label()}.csv")
        self._set_vintage([csv_path])
        return [csv_path]

    # -- normalize -----------------------------------------------------------
    def normalize(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Return `{"airport_month": df, "otp_taxi_hist": df, "otp_peak": df}`.

        Aggregates each raw file down to airport-month summaries; nothing row-level is
        kept in the returned frames or written to the store.
        """
        self._set_vintage(paths)
        frames = [pd.read_csv(p, usecols=list(SOURCE_COLUMNS)) for p in paths]
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SOURCE_COLUMNS)
        if raw.empty:
            self._period_start = self._period_end = None
            return {
                "airport_month": pd.DataFrame(columns=AIRPORT_MONTH_COLUMNS),
                "otp_taxi_hist": pd.DataFrame(columns=TAXI_HIST_COLUMNS),
                "otp_peak": pd.DataFrame(columns=OTP_PEAK_COLUMNS),
            }
        raw["period"] = raw["Year"].astype(str) + "-" + raw["Month"].astype(str).str.zfill(2)
        self._period_start = raw["period"].min()
        self._period_end = raw["period"].max()
        return {
            "airport_month": self._airport_month_frame(raw),
            "otp_taxi_hist": self._taxi_hist_frame(raw),
            "otp_peak": self._peak_frame(raw),
        }

    def _airport_month_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        not_cancelled = raw[raw["Cancelled"] == 0]
        # `cancelled_dep` is the only measure that needs the cancelled rows themselves — every
        # other Origin-based sum is computed on `not_cancelled` explicitly, not by relying on
        # NaN-skipping: DepDelayMinutes can be non-null even on a cancelled flight (verified —
        # a pushback delay recorded before the eventual cancellation), which would otherwise
        # silently inflate dep_delay_min_sum past what dep_count divides into.
        dep = (
            not_cancelled.groupby(["Origin", "period"])
            .agg(
                dep_count=("Origin", "size"),
                dep_delay_min_sum=("DepDelayMinutes", "sum"),
                carrier_delay_min=("CarrierDelay", "sum"),
                weather_delay_min=("WeatherDelay", "sum"),
                nas_delay_min=("NASDelay", "sum"),
                security_delay_min=("SecurityDelay", "sum"),
                late_aircraft_delay_min=("LateAircraftDelay", "sum"),
            )
            .reset_index()
            .rename(columns={"Origin": "iata"})
        )
        cancelled = (
            raw.groupby(["Origin", "period"])["Cancelled"]
            .sum()
            .reset_index(name="cancelled_dep")
            .rename(columns={"Origin": "iata"})
        )
        dep = dep.merge(cancelled, on=["iata", "period"], how="outer")
        dep["dep_count"] = dep["dep_count"].fillna(0)
        dep["cancelled_dep"] = dep["cancelled_dep"].fillna(0)
        arr = (
            not_cancelled.groupby(["Dest", "period"])
            .agg(
                arrivals=("Dest", "size"),
                arr_late15=("ArrDel15", "sum"),
            )
            .reset_index()
            .rename(columns={"Dest": "iata"})
        )
        dep_long = dep.melt(
            id_vars=["iata", "period"], value_vars=list(DEP_MEASURES), var_name="measure", value_name="value"
        )
        arr_long = arr.melt(
            id_vars=["iata", "period"], value_vars=list(ARR_MEASURES), var_name="measure", value_name="value"
        )
        # An airport with e.g. zero non-cancelled departures that month has no honest
        # dep_delay_min_sum (not zero — absent): drop rather than invent.
        long = pd.concat([dep_long, arr_long], ignore_index=True).dropna(subset=["value"])
        long["source_id"] = self.id
        long["vintage"] = self.row_vintage()
        return long[list(AIRPORT_MONTH_COLUMNS)].sort_values(["iata", "period", "measure"]).reset_index(drop=True)

    def _taxi_hist_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        taxi = raw.dropna(subset=["TaxiOut"]).copy()
        if taxi.empty:
            return pd.DataFrame(columns=TAXI_HIST_COLUMNS)
        taxi["minute_bucket"] = taxi["TaxiOut"].astype(int).clip(upper=MAX_TAXI_BUCKET)
        hist = (
            taxi.groupby(["Origin", "period", "minute_bucket"])
            .size()
            .reset_index(name="n")
            .rename(columns={"Origin": "iata"})
        )
        hist["source_id"] = self.id
        hist["vintage"] = self.row_vintage()
        return hist[list(TAXI_HIST_COLUMNS)].sort_values(["iata", "period", "minute_bucket"]).reset_index(drop=True)

    def _peak_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        not_cancelled = raw[raw["Cancelled"] == 0]
        dep_events = not_cancelled[["Origin", "period", "DayofMonth", "CRSDepTime"]].rename(
            columns={"Origin": "iata", "CRSDepTime": "time"}
        )
        arr_events = not_cancelled[["Dest", "period", "DayofMonth", "CRSArrTime"]].rename(
            columns={"Dest": "iata", "CRSArrTime": "time"}
        )
        events = pd.concat([dep_events, arr_events], ignore_index=True)
        events["hour"] = _hour_of(events["time"])
        events = events.dropna(subset=["hour"])
        hourly = (
            events.groupby(["iata", "period", "DayofMonth", "hour"]).size().reset_index(name="ops")
        )
        days = sorted(raw["DayofMonth"].unique())
        grid = pd.MultiIndex.from_product([days, HOURS_IN_DAY], names=["DayofMonth", "hour"]).to_frame(
            index=False
        )
        rows: list[dict[str, object]] = []
        for (iata, period), group in hourly.groupby(["iata", "period"]):
            merged = grid.merge(group[["DayofMonth", "hour", "ops"]], on=["DayofMonth", "hour"], how="left")
            merged["ops"] = merged["ops"].fillna(0)
            rows.append(
                {
                    "iata": iata,
                    "period": period,
                    "p95_hourly_ops": float(merged["ops"].quantile(0.95)),
                    "max_hourly_ops": int(merged["ops"].max()),
                }
            )
        out = pd.DataFrame(rows, columns=["iata", "period", "p95_hourly_ops", "max_hourly_ops"])
        out["source_id"] = self.id
        out["vintage"] = self.row_vintage()
        return out[list(OTP_PEAK_COLUMNS)].sort_values(["iata", "period"]).reset_index(drop=True)

    # -- provenance ----------------------------------------------------------
    def _set_vintage(self, paths: list[Path]) -> None:
        """Derive vintage/fetched_at from the raw file's mtime (see `file_vintage`)."""
        self._vintage, self._fetched_at = file_vintage(paths)

    def row_vintage(self) -> str:
        """Per-row vintage: the raw file's date ("YYYY-MM-DD")."""
        return self._vintage

    def vintage(self) -> SourceVintage:
        return SourceVintage(
            source_id=self.id,
            description=(
                "BTS On-Time Performance — monthly delay/cancellation/taxi-out/peak-hour "
                "measures aggregated from row-level flights (trailing 12 months only, see "
                "module docstring)"
            ),
            period_start=self._period_start,
            period_end=self._period_end,
            fetched_at=self._fetched_at,
            url=URL_TEMPLATE,
        )
