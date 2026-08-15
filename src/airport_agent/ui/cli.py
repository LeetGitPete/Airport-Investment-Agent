"""Non-interactive CLI harness: `python -m airport_agent.ui.cli "question" [--session id] [--json] ...`.

Loud failures (design 03 §Failure policy): `LLMError` prints its (already actionable) message verbatim to
stderr and exits 1; any other exception — including a failure to obtain the `App` itself (e.g.
`build_app()`/the configured factory raising) or to resolve the session — prints
`f"{type(e).__name__}: {e}"` to stderr and exits 2. Every failure route below returns 1 or 2; nothing
escapes as a bare traceback.
"""
from __future__ import annotations

import argparse
import sys

from airport_agent.contracts import LLMError

from .bootstrap import get_app
from .textfmt import answer_to_json, answer_to_text


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airport-agent", description="Ask the Airport Investment Intelligence Agent.")
    p.add_argument("question", help="the question to ask")
    p.add_argument("--session", help="session id to load (unknown id -> a new session is created)")
    p.add_argument("--json", action="store_true", help="print the Answer as JSON instead of plain text")
    p.add_argument("--horizon", help="default horizon (e.g. 12m, 3y, 5y, 10y)")
    p.add_argument("--preset", help="default scoring preset")
    p.add_argument("--peer-group", help="default peer group (hub_class, region, all)")
    return p


def _defaults_from(args: argparse.Namespace) -> dict[str, str] | None:
    defaults: dict[str, str] = {}
    if args.horizon is not None:
        defaults["horizon"] = args.horizon
    if args.preset is not None:
        defaults["scoring_preset"] = args.preset
    if args.peer_group is not None:
        defaults["peer_group"] = args.peer_group
    return defaults or None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        app = get_app()

        if args.session:
            try:
                state = app.sessions.load(args.session)
            except KeyError:
                state = app.sessions.new()
                print(state.session_id, file=sys.stderr)
        else:
            state = app.sessions.new()

        answer = app.answer(args.question, state, defaults=_defaults_from(args))
    except LLMError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - deliberate catch-all per failure policy
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(answer_to_json(answer) if args.json else answer_to_text(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
