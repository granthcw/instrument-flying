"""Great-circle geometry helpers.

Distances are in nautical miles unless a name says otherwise. The backtest
only ever asks "is this point within R of the field", so a spherical earth is
plenty: the worst-case error over a 20 nm radius is a few metres.
"""

from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065
NM_PER_KM = 0.539957


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lon: float, radius_nm: float) -> tuple[float, float, float, float]:
    """Lat/lon box that fully contains the radius circle.

    Returned as (min_lat, max_lat, min_lon, max_lon). Used to cheaply discard
    the ~99.9% of GLM flashes that are nowhere near the field before paying for
    a haversine on each one. The box is deliberately a superset of the circle,
    so callers must still range-check survivors.
    """
    dlat = math.degrees(radius_nm / EARTH_RADIUS_NM)
    # Guard the cosine: at the poles a fixed-width box degenerates.
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        return (-90.0, 90.0, -180.0, 180.0)
    dlon = math.degrees(radius_nm / (EARTH_RADIUS_NM * cos_lat))
    # The box is exactly tangent to the circle at the cardinal points, so
    # rounding can place a point sitting precisely on the radius a fraction of
    # an ulp outside it. Pad by ~1 cm so the superset guarantee actually holds;
    # survivors are still range-checked by haversine.
    eps = 1e-9
    return (lat - dlat - eps, lat + dlat + eps, lon - dlon - eps, lon + dlon + eps)


def km_to_nm(km: float) -> float:
    return km * NM_PER_KM


def nm_to_km(nm: float) -> float:
    return nm / NM_PER_KM
