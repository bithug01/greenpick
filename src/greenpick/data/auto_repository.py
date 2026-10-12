"""Auto router: pick the right live source per region.

- US regions (have an `eia_ba`)      -> EIA
- EU regions (have an `entsoe_eic`)  -> ENTSO-E
- anything else                      -> mock (honestly labelled)

Lets a single GREENPICK_CARBON_SOURCE=auto give live data on both continents.
"""
from __future__ import annotations

from ..models import CarbonReading, Provider, HourlyCarbon
from .mock_repository import MockCarbonRepository
from .eia_repository import EIARepository
from .entsoe_repository import ENTSOERepository
from .static_data import region_meta


class AutoRepository:
    def __init__(self, eia_key: str, entsoe_token: str, cache_ttl_seconds: int = 1800) -> None:
        self._eia = EIARepository(eia_key, cache_ttl_seconds)
        self._entsoe = ENTSOERepository(entsoe_token, cache_ttl_seconds)
        self._mock = MockCarbonRepository()

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        meta = region_meta(provider, region) or {}
        if meta.get("eia_ba"):
            return await self._eia.carbon_now(provider, region)
        if meta.get("entsoe_eic"):
            return await self._entsoe.carbon_now(provider, region)
        return await self._mock.carbon_now(provider, region)

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        meta = region_meta(provider, region) or {}
        if meta.get("eia_ba"):
            return await self._eia.carbon_history(provider, region)
        if meta.get("entsoe_eic"):
            return await self._entsoe.carbon_history(provider, region)
        return await self._mock.carbon_history(provider, region)
