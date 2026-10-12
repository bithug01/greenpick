"""EIA-930 carbon source (US balancing authorities).

Free US government data — no license tiers or activation gating (unlike Electricity Maps'
free tier). We pull the latest hourly generation mix by fuel type for a region's balancing
authority, then weight by per-fuel emission factors to get a directional gCO2/kWh.

Key (free, instant): https://www.eia.gov/opendata/  -> Register.
Endpoint: GET https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/
  params: api_key, frequency=hourly, data[0]=value, facets[respondent][]=<BA>,
          sort by period desc, length=... (we grab the most recent hour's fuels)
  rows:   { period, respondent, fueltype (COL/NG/NUC/WAT/WND/SUN/...), value (MWh), ... }

Carbon intensity = sum(gen_fuel * factor_fuel) / sum(gen_fuel).  Directional, not audited.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from ..models import CarbonReading, Provider, HourlyCarbon
from .mock_repository import MockCarbonRepository
from .static_data import region_meta, emission_factors

log = logging.getLogger("greenpick.eia")

_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"


class EIARepository:
    def __init__(self, api_key: str, cache_ttl_seconds: int = 1800) -> None:
        self._key = api_key
        self._ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, CarbonReading]] = {}  # BA -> (fetched_at, reading)
        self._fallback = MockCarbonRepository()
        self._warned_no_key = False

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        meta = region_meta(provider, region) or {}
        ba = meta.get("eia_ba")

        if not self._key:
            if not self._warned_no_key:
                log.warning("No EIA_API_KEY set — falling back to mock. Register free at "
                            "https://www.eia.gov/opendata/")
                self._warned_no_key = True
            return await self._fallback.carbon_now(provider, region)
        if not ba:
            # Non-US region (no balancing authority) -> EIA can't help; mock, labelled.
            return await self._fallback.carbon_now(provider, region)

        hit = self._cache.get(ba)
        if hit and (time.time() - hit[0]) < self._ttl:
            cached = hit[1]
            return cached.model_copy(update={"region": region, "provider": provider, "quality": "cached"})

        rows = await self._fetch_rows(ba)
        if rows is None:
            return await self._fallback.carbon_now(provider, region)
        reading = self._mix_to_reading(provider, region, ba, rows)
        if reading is None:
            return await self._fallback.carbon_now(provider, region)
        self._cache[ba] = (time.time(), reading)
        return reading

    async def _fetch_rows(self, ba: str) -> list | None:
        """Fetch recent hourly fuel rows for a BA. Returns None on auth/network error
        (caller falls back to mock)."""
        try:
            params = {
                "api_key": self._key,
                "frequency": "hourly",
                "data[0]": "value",
                "facets[respondent][]": ba,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": "500",   # ~60 recent hours x fuels — enough for history too
            }
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.get(_URL, params=params)
            if resp.status_code in (401, 403):
                log.warning("EIA rejected the key (HTTP %s) — using mock. Check EIA_API_KEY.",
                            resp.status_code)
                return None
            resp.raise_for_status()
            return resp.json().get("response", {}).get("data", [])
        except Exception as e:
            log.debug("EIA call failed for BA %s (%s) — mock fallback", ba, e)
            return None

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """Per-hour carbon intensity from the recent EIA window (same call as carbon_now)."""
        meta = region_meta(provider, region) or {}
        ba = meta.get("eia_ba")
        if not self._key or not ba:
            return await self._fallback.carbon_history(provider, region)
        rows = await self._fetch_rows(ba)
        if not rows:
            return await self._fallback.carbon_history(provider, region)
        factors = emission_factors()["factors_g_co2_per_kwh"]
        # Group fuel rows by hour, compute weighted intensity per hour.
        by_hour: dict[str, list] = {}
        for r in rows:
            by_hour.setdefault(r.get("period"), []).append(r)
        out: list[HourlyCarbon] = []
        for period, hour_rows in by_hour.items():
            total = weighted = 0.0
            for r in hour_rows:
                fuel = r.get("fueltype")
                try:
                    mwh = float(r.get("value") or 0)
                except (TypeError, ValueError):
                    continue
                if mwh > 0 and fuel in factors:
                    total += mwh
                    weighted += mwh * factors[fuel]
            if total > 0:
                out.append(HourlyCarbon(period=period, g_co2_per_kwh=round(weighted / total, 1)))
        return out or await self._fallback.carbon_history(provider, region)

    def _mix_to_reading(self, provider: Provider, region: str, ba: str, rows: list) -> CarbonReading | None:
        """Take the most recent hour's fuel rows, weight by emission factors -> gCO2/kWh."""
        if not rows:
            return None
        # Rows are sorted period desc; the first row's period is the latest available hour.
        latest_period = rows[0].get("period")
        factors = emission_factors()["factors_g_co2_per_kwh"]

        total_mwh = 0.0
        weighted = 0.0
        for r in rows:
            if r.get("period") != latest_period:
                break  # only the most recent hour
            fuel = r.get("fueltype")
            try:
                mwh = float(r.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if mwh <= 0 or fuel not in factors:
                continue
            total_mwh += mwh
            weighted += mwh * factors[fuel]

        if total_mwh <= 0:
            return None
        intensity = weighted / total_mwh
        return CarbonReading(
            region=region,
            provider=provider,
            g_co2_per_kwh=round(intensity, 1),
            source="eia",
            timestamp=str(latest_period or datetime.now(timezone.utc).isoformat()),
            quality="live",
        )
