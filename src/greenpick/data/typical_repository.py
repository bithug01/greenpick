"""Typical carbon source — the fallback whenever live data isn't available.

Serves, for the current calendar month, a region's average grid carbon intensity and its average
24-hour profile (UTC), computed from 12 months of real hourly data (EIA-930 / ENTSO-E A75) by
scripts/refresh_typical.py and bundled as data/typical.json. Labelled quality="typical": real
data, but a monthly norm, not a current reading.

Regions the file doesn't cover (no free live source, e.g. Sydney) — or a month it lacks — fall
through to MockCarbonRepository's hand-set values, still labelled quality="mock".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models import CarbonReading, HourlyCarbon, Provider
from .mock_repository import MockCarbonRepository
from .static_data import typical


def typical_entry(provider: str, region: str) -> Optional[dict]:
    """The typical.json entry for a region (source, from, to, months), or None."""
    return typical().get("regions", {}).get(provider, {}).get(region)


def _month(entry: dict) -> Optional[dict]:
    return entry.get("months", {}).get(str(datetime.now(timezone.utc).month))


class TypicalCarbonRepository:
    def __init__(self) -> None:
        self._mock = MockCarbonRepository()

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        entry = typical_entry(provider, region)
        month = _month(entry) if entry else None
        if not month:
            return await self._mock.carbon_now(provider, region)
        return CarbonReading(
            region=region,
            provider=provider,
            g_co2_per_kwh=month["avg_g_co2_per_kwh"],
            source=f"typical_{entry['source']}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            quality="typical",
        )

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """This month's average day, hour by hour. Periods are 'H15Z' style: an hour of the day in
        UTC, not a date — it's a typical pattern, not a record of specific past hours."""
        entry = typical_entry(provider, region)
        month = _month(entry) if entry else None
        if not month:
            return await self._mock.carbon_history(provider, region)
        return [HourlyCarbon(period=f"H{h:02d}Z", g_co2_per_kwh=g)
                for h, g in enumerate(month["hourly_utc"]) if g is not None]
