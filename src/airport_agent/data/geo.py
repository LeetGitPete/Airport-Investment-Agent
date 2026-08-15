"""Geographic helpers for the data layer (no external deps beyond stdlib math)."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_MI = 3958.8


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles between two lat/lon points."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return _EARTH_RADIUS_MI * c
