# Hygiene sweep — findings (non-trivial, NOT fixed)

Everything here is deliberately **not fixed**: it is ambiguous, off-design, behaviour-changing, in a frozen
file, or otherwise a human's call. Trivial fixes were applied directly and are listed in `REPORT.md` instead.

Format per the project escalation protocol: what · why it matters · options · recommendation · blocked.

### F-001 — `otp_peak` day-grid spans every month in the refresh, not each month's own days   [severity: medium] [src/airport_agent/data/adapters/bts_otp.py:299]
what:            `_peak_frame` builds ONE zero-fill grid for all periods in the call:

                     days = sorted(raw["DayofMonth"].unique())
                     grid = pd.MultiIndex.from_product([days, HOURS_IN_DAY], ...)
                     for (iata, period), group in hourly.groupby(["iata", "period"]):
                         merged = grid.merge(group[...], how="left")
                         merged["ops"] = merged["ops"].fillna(0)

                 `refresh._ingest_one` fetches every month of the trailing window and calls
                 `normalize(all_paths)` once, so `raw` spans ~12 months and `days` is always
                 1..31. A 28-day February is then zero-filled over 31x24 = 744 hour-slots
                 instead of its own 28x24 = 672 — 72 phantom idle hours that never existed.
                 Reproduced on synthetic data: identical February input yields
                 `p95_hourly_ops = 1.0` when February is refreshed alone and `0.0` when
                 February and March are refreshed together.
why it matters:  `p95_hourly_ops` feeds `peak_hour_ops_ratio` (tier B, P2), a scored metric.
                 The phantom zeros drag the 95th percentile down, so short months look quieter
                 than they were and the airport reads as less capacity-constrained. The size of
                 the error depends on which months happen to be in the refresh window, so the
                 same airport's stored number changes with refresh scope rather than with data.
                 It is a wrong number, not a missing one — nothing flags it.
options:         1) Build the grid per period from that period's own days
                    (`group["DayofMonth"].unique()`, or a calendar month-length lookup).
                 2) Derive the day set per period inside the groupby from `raw`, keeping one
                    grid per (period) rather than one global grid.
                 3) Leave as-is and document it as a known approximation in the limitations log.
recommendation:  Option 1 — it is the smallest change and makes the metric independent of
                 refresh scope, which is the property that is actually broken. It changes stored
                 values for every short month, so it needs a snapshot rebuild and a golden
                 refresh; that is why it is logged here rather than fixed in this sweep.
blocked:         nothing — `peak_hour_ops_ratio` is computed and scored today; this changes its
                 value for affected airports.

