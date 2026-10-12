"""Mock carbon source — deterministic, offline, the default.

Lets the whole server run and be tested without any API token or network. Values are
plausible, stable per region, and clearly labelled quality="mock" so nothing mistakes
them for real readings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from ..models import CarbonReading, Provider

# Rough, stable gCO2/kWh per approximate grid zone (illustrative, NOT real-time).
_ZONE_INTENSITY = {
    "US-MIDA-PJM": 350,
    "US-NW-PACW": 110,
    "US-MIDW-MISO": 430,
    "IE": 290,
    "SE": 25,
    "FI": 70,
    "AU-NSW": 580,
}
_DEFAULT = 400


class MockCarbonRepository:
    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        from .static_data import region_meta
        meta = region_meta(provider, region) or {}
        zone = meta.get("zone", "")
        intensity = _ZONE_INTENSITY.get(zone, _DEFAULT)
        return CarbonReading(
            region=region,
            provider=provider,
            g_co2_per_kwh=float(intensity),
            source="mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
            quality="mock",
        )
