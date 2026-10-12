"""Carbon data repository: the one interface every source implements.

Services depend ONLY on this Protocol, so sources (mock / Electricity Maps / ENTSO-E /
EIA) are swappable via config without touching business logic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from ..models import CarbonReading, Provider


@runtime_checkable
class CarbonRepository(Protocol):
    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        """Current grid carbon intensity for one region. Implementations should
        degrade gracefully (cached -> annual average) and set CarbonReading.quality
        to reflect what was actually returned."""
        ...
