"""Geographic latency estimate: great-circle distance -> rough round-trip ms.

A deliberate approximation (speed of light in fiber + routing overhead), good enough
for "is this region far from my users?" Not a measured ping.
"""
from __future__ import annotations

import math
from ..models import GeoPoint, Provider
from ..data.static_data import region_meta

# Rough rule of thumb: ~fiber latency plus routing/queuing overhead.
# ~0.0107 ms per km one-way for light in fiber; double for round trip; add a fixed overhead.
_MS_PER_KM_RTT = 0.0107 * 2 * 1.4   # 1.4 fudge for non-great-circle routing
_FIXED_OVERHEAD_MS = 10.0


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    r = 6371.0
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(a.lat)) * math.cos(math.radians(b.lat)) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def estimate_latency_ms(provider: Provider, region: str, user: GeoPoint) -> float | None:
    meta = region_meta(provider, region)
    if not meta:
        return None
    region_pt = GeoPoint(lat=meta["lat"], lon=meta["lon"])
    km = _haversine_km(user, region_pt)
    return round(_FIXED_OVERHEAD_MS + km * _MS_PER_KM_RTT, 1)
