"""Registry of source adapters.

Each adapter module registers itself with `@register` under `cls.id`. This
module imports every adapter module that exists so the registration side
effect runs; new adapter modules append themselves to the import block below.
"""
from __future__ import annotations

ADAPTERS: dict[str, type] = {}


def register(cls: type) -> type:
    """Class decorator: add `cls` to `ADAPTERS` keyed by `cls.id`."""
    ADAPTERS[cls.id] = cls
    return cls


# --- adapter modules (import for registration side effect) -----------------
# Later tasks append one import per adapter here.
from airport_agent.data.adapters import faa_npias as _faa_npias  # noqa: E402, F401
from airport_agent.data.adapters import faa_taf as _faa_taf  # noqa: E402, F401
from airport_agent.data.adapters import ourairports as _ourairports  # noqa: E402, F401
# -----------------------------------------------------------------------------
