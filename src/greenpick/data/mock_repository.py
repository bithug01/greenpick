"""Mock carbon source — deterministic, offline, the default.

Lets the whole server run and be tested without any API token or network. Values are
plausible, stable per region, and clearly labelled quality="mock" so nothing mistakes
them for real readings.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from ..models import CarbonReading, Provider, HourlyCarbon

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

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """Synthetic 24h curve around the region's base intensity: cleaner overnight / midday
        (solar), dirtier at evening peak — a plausible shape so scheduling logic is testable offline."""
        from .static_data import region_meta
        meta = region_meta(provider, region) or {}
        base = _ZONE_INTENSITY.get(meta.get("zone", ""), _DEFAULT)
        out: list[HourlyCarbon] = []
        for h in range(24):
            # +/-30% swing: trough ~04:00 and ~13:00, peak ~19:00.
            factor = 1 + 0.3 * math.sin((h - 9) / 24 * 2 * math.pi) \
                     - 0.15 * math.cos((h - 13) / 24 * 4 * math.pi)
            out.append(HourlyCarbon(period=f"H{h:02d}", g_co2_per_kwh=round(base * factor, 1)))
        return out
