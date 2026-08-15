"""Shared definition of a "commercial" airport, used by `service.py` (`list_airports`) and
`derived/p3_market.py` (`competing_seats_100mi`).

Plan Task 14: "commercial = present in Socrata (`airport_year.enplanements`) or TAF
(`taf_history.enplanements`) with a positive value." This is computed at query time from
the traffic tables rather than persisted on `airports.commercial` (which stays at the
OurAirports placeholder `False` — see `adapters/ourairports.py`): a stored flag would need
its own refresh step and could drift from the tables that actually define it.
"""
from __future__ import annotations

import pandas as pd

#: `a` must be the alias of the `airports` table in the enclosing query.
COMMERCIAL_EXISTS_SQL = """(
    EXISTS (SELECT 1 FROM airport_year y WHERE y.iata = a.iata AND y.measure = 'enplanements' AND y.value > 0)
    OR EXISTS (SELECT 1 FROM taf_history t WHERE t.faa_locid = a.faa_locid AND t.enplanements > 0)
)"""


def commercial_airports(con) -> pd.DataFrame:
    """`(iata, lat, lon)` for every commercial airport (see module docstring)."""
    return con.execute(f"SELECT a.iata, a.lat, a.lon FROM airports a WHERE {COMMERCIAL_EXISTS_SQL}").df()  # noqa: S608
