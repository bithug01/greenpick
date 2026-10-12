"""Electricity Maps free-tier carbon source.

Live grid carbon intensity per zone, with honest degradation:
  - zone not on the free tier / not mapped  -> mock fallback (labelled quality="mock")
  - network / rate-limit error              -> mock fallback
  - bad or missing token                    -> mock fallback (warned once; it's a config issue)
  - value flagged isEstimated by the API    -> quality="live_estimated" (still real, but modelled)

Free tier + token: https://electricitymaps.com/free-tier
API: GET https://api.electricitymap.org/v3/carbon-intensity/latest?zone=XX
     header: auth-token: <token>
     -> { "carbonIntensity": <gCO2/kWh>, "datetime": "...", "isEstimated": bool, ... }
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from ..models import CarbonReading, Provider, HourlyCarbon
from .mock_repository import MockCarbonRepository
from .static_data import region_meta

log = logging.getLogger("greenpick.electricitymaps")

_BASE = "https://api.electricitymap.org/v3/carbon-intensity/latest"


class ElectricityMapsRepository:
    def __init__(self, token: str, cache_ttl_seconds: int = 1800) -> None:
        self._token = token
        self._ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, CarbonReading]] = {}  # zone -> (fetched_at, reading)
        self._fallback = MockCarbonRepository()
        self._token_rejected = False   # once a 401/403 is seen, stop calling with a bad key
        self._warned_no_token = False

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        # Not implemented for this (unused) source; degrade to the fallback curve.
        return await self._fallback.carbon_history(provider, region)

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        meta = region_meta(provider, region)
        zone = (meta or {}).get("zone")

        if not self._token:
            if not self._warned_no_token:
                log.warning("No ELECTRICITYMAPS_TOKEN set — falling back to mock data. "
                            "Get a free key at https://electricitymaps.com/free-tier")
                self._warned_no_token = True
            return await self._fallback.carbon_now(provider, region)

        if self._token_rejected or not zone:
            # Bad key already seen, or no zone mapping for this region -> mock, labelled.
            return await self._fallback.carbon_now(provider, region)

        # Fresh cache hit?
        hit = self._cache.get(zone)
        if hit and (time.time() - hit[0]) < self._ttl:
            cached = hit[1]
            return cached.model_copy(update={
                "region": region, "provider": provider,
                "quality": "cached" if cached.quality in ("live", "live_estimated", "cached") else cached.quality,
            })

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(_BASE, params={"zone": zone},
                                        headers={"auth-token": self._token})

            if resp.status_code in (401, 403):
                # Config problem, not a per-region issue. Warn once, then stop trying.
                self._token_rejected = True
                log.warning("Electricity Maps rejected the token (HTTP %s) — using mock data. "
                            "Check ELECTRICITYMAPS_TOKEN.", resp.status_code)
                return await self._fallback.carbon_now(provider, region)
            if resp.status_code == 404:
                # Zone not covered on this plan/mapping. Silent per-region fallback.
                log.debug("Zone %s not available (404) — mock fallback for %s/%s", zone, provider, region)
                return await self._fallback.carbon_now(provider, region)
            resp.raise_for_status()

            payload = resp.json()
            intensity = payload.get("carbonIntensity")
            if intensity is None:
                return await self._fallback.carbon_now(provider, region)

            reading = CarbonReading(
                region=region,
                provider=provider,
                g_co2_per_kwh=float(intensity),
                source="electricitymaps",
                timestamp=str(payload.get("datetime", datetime.now(timezone.utc).isoformat())),
                quality="live_estimated" if payload.get("isEstimated") else "live",
            )
            self._cache[zone] = (time.time(), reading)
            return reading

        except Exception as e:
            # Network/parse/rate-limit -> mock fallback rather than erroring the tool.
            log.debug("Electricity Maps call failed for zone %s (%s) — mock fallback", zone, e)
            return await self._fallback.carbon_now(provider, region)
