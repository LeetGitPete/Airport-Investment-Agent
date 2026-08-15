"""`python -m airport_agent.data refresh [--sources a,b] [--period YYYY-MM] [--full] [--check]
[--snapshot PATH]` — see `refresh.py`'s module docstring for period-window semantics and the
cron / Windows Task Scheduler lines.

Exit codes: 0 even when individual sources fail (they are listed in the printed table —
"snapshot keeps last good", per-source failure isolation is the point); 2 on invalid CLI args.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from airport_agent.data.adapters.base import Period
from airport_agent.data.paths import default_snapshot_path, raw_cache_dir
from airport_agent.data.refresh import refresh, staleness
from airport_agent.data.sources_config import load_sources


def _parse_period(text: str) -> Period:
    try:
        year_s, month_s = text.split("-")
        return Period(year=int(year_s), month=int(month_s))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(f"--period must be YYYY-MM, got {text!r}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m airport_agent.data", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    refresh_p = sub.add_parser("refresh", help="fetch/normalize/write every bulk source, then rebuild derived metrics")
    refresh_p.add_argument("--sources", type=str, default=None, help="comma-separated source ids (default: all bulk sources)")
    refresh_p.add_argument("--period", type=_parse_period, default=None, help="YYYY-MM (bts_t100/bts_otp only)")
    refresh_p.add_argument("--full", action="store_true", help="fetch the full trailing window (bts_t100/bts_otp) instead of just the latest month")
    refresh_p.add_argument("--check", action="store_true", help="print staleness (vs cadence_days) instead of refreshing")
    refresh_p.add_argument("--snapshot", type=Path, default=None, help="snapshot path (default: data/snapshot/airports.duckdb)")
    refresh_p.add_argument("--cache-dir", type=Path, default=None, help="raw download cache dir (default: data/raw)")

    return parser


def _print_staleness_table(snapshot: Path | None) -> None:
    rows = staleness(snapshot)
    width = max(len(r["source_id"]) for r in rows)
    print(f"{'source_id'.ljust(width)}  status   age_days  cadence_days  fetched_at")
    for r in rows:
        age = "n/a" if r["age_days"] is None else str(r["age_days"])
        fetched = r["fetched_at"] or "n/a"
        print(f"{r['source_id'].ljust(width)}  {r['status']:<7}  {age:>8}  {r['cadence_days']:>12}  {fetched}")


def _print_refresh_report(report) -> None:
    width = max((len(r.source_id) for r in report.results), default=8)
    print(f"{'source_id'.ljust(width)}  status  rows     seconds")
    for r in report.results:
        status = "ok" if r.ok else "FAILED"
        print(f"{r.source_id.ljust(width)}  {status:<6}  {r.rows:>7}  {r.seconds:>7.1f}" + (f"  -- {r.error}" if r.error else ""))
    print()
    print("derived metrics rebuilt:")
    for metric_id, count in sorted(report.derived_row_counts.items()):
        print(f"  {metric_id}: {count} rows")
    if report.failed:
        print()
        print(f"{len(report.failed)} source(s) failed (snapshot kept the last good data for each): "
              f"{', '.join(r.source_id for r in report.failed)}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "refresh":
        parser.error(f"unknown command: {args.command}")
        return 2

    if args.check:
        _print_staleness_table(args.snapshot)
        return 0

    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    known = set(load_sources())
    if sources:
        unknown = [s for s in sources if s not in known]
        if unknown:
            parser.error(f"unknown source id(s): {', '.join(unknown)} (known: {', '.join(sorted(known))})")
            return 2

    report = refresh(
        sources=sources,
        period=args.period,
        full=args.full,
        cache_dir=args.cache_dir or raw_cache_dir(),
        snapshot_path=args.snapshot or default_snapshot_path(),
    )
    _print_refresh_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
