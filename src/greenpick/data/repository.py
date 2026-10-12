"""Carbon data repository: the one interface every source implements.

Services depend ONLY on this Protocol, so sources (mock / Electricity Maps / ENTSO-E /
EIA) are swappable via config without touching business logic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from ..models import CarbonReading, Provider


from ..models import HourlyCarbon


@runtime_checkable
class CarbonRepository(Protocol):
    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        """Current grid carbon intensity for one region. Implementations should
        degrade gracefully (cached -> annual average) and set CarbonReading.quality
        to reflect what was actually returned."""
        ...

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """Recent hourly carbon intensity for a region (for scheduling deferrable work).
        Return [] if the source doesn't support history for this region — callers must
        handle the empty case. Default implementations may return []."""
        ...
