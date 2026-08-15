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
from airport_agent.data.adapters import bts_otp as _bts_otp  # noqa: E402, F401
from airport_agent.data.adapters import bts_socrata as _bts_socrata  # noqa: E402, F401
from airport_agent.data.adapters import bts_t100 as _bts_t100  # noqa: E402, F401
from airport_agent.data.adapters import census_cbsa as _census_cbsa  # noqa: E402, F401
from airport_agent.data.adapters import curated as _curated  # noqa: E402, F401
from airport_agent.data.adapters import faa_aip as _faa_aip  # noqa: E402, F401
from airport_agent.data.adapters import faa_nasstatus as _faa_nasstatus  # noqa: E402, F401
from airport_agent.data.adapters import faa_npias as _faa_npias  # noqa: E402, F401
from airport_agent.data.adapters import faa_taf as _faa_taf  # noqa: E402, F401
from airport_agent.data.adapters import ourairports as _ourairports  # noqa: E402, F401
# -----------------------------------------------------------------------------
