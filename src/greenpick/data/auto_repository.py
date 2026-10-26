"""Auto router: pick the right live source per region.

- US regions (have an `eia_ba`)        -> EIA
- EU regions (have an `entsoe_eic`)    -> ENTSO-E
- Canadian regions (have a `ca_source`) -> Hydro-Québec / IESO (no key needed)
- anything else                        -> typical / mock fallback (honestly labelled)

Lets a single GREENPICK_CARBON_SOURCE=auto give live data on all three.
"""
from __future__ import annotations

from ..models import CarbonReading, Provider, HourlyCarbon, ForecastHour
from .typical_repository import TypicalCarbonRepository
from .eia_repository import EIARepository
from .entsoe_repository import ENTSOERepository
from .canada_repository import CanadaRepository
from .static_data import region_meta


class AutoRepository:
    def __init__(self, eia_key: str, entsoe_token: str, cache_ttl_seconds: int = 1800) -> None:
        self._eia = EIARepository(eia_key, cache_ttl_seconds)
        self._entsoe = ENTSOERepository(entsoe_token, cache_ttl_seconds)
        self._canada = CanadaRepository(cache_ttl_seconds)
        self._mock = TypicalCarbonRepository()

    def _route(self, provider: Provider, region: str):
        meta = region_meta(provider, region) or {}
        if meta.get("eia_ba"):
            return self._eia
        if meta.get("entsoe_eic"):
            return self._entsoe
        if meta.get("ca_source"):
            return self._canada
        return self._mock

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        return await self._route(provider, region).carbon_now(provider, region)

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        return await self._route(provider, region).carbon_history(provider, region)

    async def renewable_forecast(self, provider: Provider, region: str, hours_ahead: int = 24
                                 ) -> list[ForecastHour]:
        """Forward renewable forecast — only EU (ENTSO-E A69) has a free one. US/other -> []
        so the scheduling layer degrades to the historical pattern, labelled honestly."""
        meta = region_meta(provider, region) or {}
        if meta.get("entsoe_eic"):
            return await self._entsoe.renewable_forecast(provider, region, hours_ahead)
        return []
