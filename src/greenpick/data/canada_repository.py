"""Canadian carbon sources: Hydro-Québec (Québec) and IESO (Ontario). Both free, no key.

- Hydro-Québec open data: hourly generation by source (hydraulique, eolien, solaire, thermique,
  autres) for the last ~48h, via the opendatasoft API. Values lag 1.5-6h; the newest hours come
  back empty until filled, so we use the latest hour that has a total.
- IESO: today's hourly output per generator, with each generator's fuel type
  (PUB_GenOutputCapability.xml, updated hourly). Hours are "hour ending" in Eastern Standard Time
  all year, so hour h of date D starts at D + (h-1)h EST = D + (h+4)h UTC.

Both are weighted with GreenPick's own per-fuel factors (emission_factors.json ->
canada_fuel_to_factor), the same way EIA and ENTSO-E mixes are, so regions compare fairly.
Production-based (imports/exports not traced), like the other sources. Falls back to the typical
monthly values when a fetch fails, with the same bounded timeouts and outage memory as ENTSO-E.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

from ..models import CarbonReading, HourlyCarbon, Provider
from ._net import REQUEST_DEADLINE_S, REQUEST_TIMEOUT, describe_error
from .static_data import emission_factors, region_meta
from .typical_repository import TypicalCarbonRepository

log = logging.getLogger("greenpick.canada")

HQ_LIVE_URL = ("https://donnees.hydroquebec.com/api/explore/v2.1/catalog/datasets/"
               "production-electricite-quebec/records")
IESO_LIVE_URL = "https://reports-public.ieso.ca/public/GenOutputCapability/PUB_GenOutputCapability.xml"
_OUTAGE_COOLDOWN_S = 300.0
_EST = timezone(timedelta(hours=-5))   # IESO publishes in EST year-round (no DST)
LABEL = {"hq": "Hydro-Québec", "ieso": "IESO"}


def _factors(source: str) -> dict[str, float]:
    return emission_factors()["canada_fuel_to_factor"][source]


def mix_to_intensity(source: str, mix: dict[str, float]) -> Optional[float]:
    """Weighted gCO2/kWh for a {fuel: MW} mix, ignoring unknown fuels and non-positive values."""
    f = _factors(source)
    parts = [(mw, f[fuel]) for fuel, mw in mix.items() if fuel in f and mw and mw > 0]
    total = sum(mw for mw, _ in parts)
    return round(sum(mw * g for mw, g in parts) / total, 1) if total > 0 else None


def hour_utc(timestamp: str) -> Optional[str]:
    """'2026-10-26T09:30:00+00:00' -> '2026-10-26T09' (UTC, floored to the hour)."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def hq_rows_to_hourly(rows: list[dict], prefix: str = "valeurs_") -> dict[str, float]:
    """Hydro-Québec records -> {UTC hour: gCO2/kWh}. Live rows use 'valeurs_<source>' fields,
    history rows use the bare source names (prefix='')."""
    out: dict[str, float] = {}
    for r in rows:
        if not r.get(f"{prefix}total"):
            continue                       # not filled in yet
        period = hour_utc(r.get("date", ""))
        mix = {k: r.get(f"{prefix}{k}") or 0.0 for k in _factors("hq")}
        g = mix_to_intensity("hq", mix)
        if period and g is not None:
            out[period] = g
    return out


def ieso_period(day: str, hour_ending: int) -> Optional[str]:
    """IESO date + hour-ending (1..24, EST) -> UTC hour the interval starts, 'YYYY-MM-DDTHH'."""
    try:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_EST) + timedelta(hours=hour_ending - 1)
    except ValueError:
        return None
    return start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def _strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def ieso_generators_to_hourly(xml_text: str) -> dict[str, float]:
    """PUB_GenOutputCapability.xml (per-generator, today) -> {UTC hour: gCO2/kWh}."""
    root = ET.fromstring(xml_text)
    day = next((e.text for e in root.iter() if _strip(e.tag) == "Date" and e.text), None)
    if not day:
        return {}
    by_hour: dict[int, dict[str, float]] = {}
    for gen in root.iter():
        if _strip(gen.tag) != "Generator":
            continue
        fuel = next((c.text for c in gen if _strip(c.tag) == "FuelType"), None)
        outputs = next((c for c in gen if _strip(c.tag) == "Outputs"), None)
        if not fuel or outputs is None:
            continue
        for out in outputs:
            vals = {_strip(c.tag): c.text for c in out}
            try:
                h, mw = int(vals.get("Hour") or 0), float(vals.get("EnergyMW") or "nan")
            except ValueError:
                continue
            if h and mw == mw:            # skip hours not reported yet (NaN)
                bucket = by_hour.setdefault(h, {})
                bucket[fuel] = bucket.get(fuel, 0.0) + mw
    out: dict[str, float] = {}
    for h, mix in by_hour.items():
        g = mix_to_intensity("ieso", mix)
        period = ieso_period(day, h)
        if g is not None and period and sum(mix.values()) > 0:
            out[period] = g
    return out


def ieso_fuel_hourly_to_hourly(xml_text: str) -> dict[str, float]:
    """PUB_GenOutputbyFuelHourly_<year>.xml (yearly, by fuel) -> {UTC hour: gCO2/kWh}."""
    root = ET.fromstring(xml_text)
    out: dict[str, float] = {}
    for daily in root.iter():
        if _strip(daily.tag) != "DailyData":
            continue
        day = next((c.text for c in daily if _strip(c.tag) == "Day"), None)
        for hourly in daily:
            if _strip(hourly.tag) != "HourlyData":
                continue
            hour = next((c.text for c in hourly if _strip(c.tag) == "Hour"), None)
            mix: dict[str, float] = {}
            for ft in hourly:
                if _strip(ft.tag) != "FuelTotal":
                    continue
                fuel = next((c.text for c in ft if _strip(c.tag) == "Fuel"), None)
                val = next((o.text for o in ft.iter() if _strip(o.tag) == "Output"), None)
                try:
                    mix[fuel] = float(val)  # type: ignore[index]
                except (TypeError, ValueError):
                    continue
            g = mix_to_intensity("ieso", mix)
            period = ieso_period(day or "", int(hour)) if hour and hour.isdigit() else None
            if g is not None and period:
                out[period] = g
    return out


class CanadaRepository:
    """Live Québec (Hydro-Québec) and Ontario (IESO) carbon, keyed off a region's ca_source."""

    def __init__(self, cache_ttl_seconds: int = 1800) -> None:
        self._ttl = cache_ttl_seconds
        self._fallback = TypicalCarbonRepository()
        self._cache: dict[str, tuple[float, dict[str, float]]] = {}
        self._down_until: dict[str, float] = {}

    async def _fetch(self, source: str) -> Optional[dict[str, float]]:
        hit = self._cache.get(source)
        if hit and time.time() - hit[0] < self._ttl:
            return hit[1]
        if time.time() < self._down_until.get(source, 0.0):
            return None
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                if source == "hq":
                    params = {"limit": "48", "order_by": "date desc", "where": "valeurs_total>0"}
                    resp = await asyncio.wait_for(client.get(HQ_LIVE_URL, params=params),
                                                  timeout=REQUEST_DEADLINE_S)
                    resp.raise_for_status()
                    hourly = hq_rows_to_hourly(resp.json().get("results", []))
                else:
                    resp = await asyncio.wait_for(client.get(IESO_LIVE_URL), timeout=REQUEST_DEADLINE_S)
                    resp.raise_for_status()
                    hourly = ieso_generators_to_hourly(resp.text)
        except Exception as e:
            log.debug("%s fetch failed (%s) — typical fallback", LABEL[source], describe_error(e))
            hourly = {}
        if not hourly:
            self._down_until[source] = time.time() + _OUTAGE_COOLDOWN_S
            return None
        self._cache[source] = (time.time(), hourly)
        return hourly

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        source = (region_meta(provider, region) or {}).get("ca_source")
        hourly = await self._fetch(source) if source else None
        if not hourly:
            return await self._fallback.carbon_now(provider, region)
        latest = max(hourly)
        cached = self._cache.get(source, (0.0, {}))[0] < time.time() - 5
        return CarbonReading(region=region, provider=provider, g_co2_per_kwh=hourly[latest],
                             source=source, timestamp=latest,  # type: ignore[arg-type]
                             quality="cached" if cached else "live")

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        source = (region_meta(provider, region) or {}).get("ca_source")
        hourly = await self._fetch(source) if source else None
        if not hourly:
            return await self._fallback.carbon_history(provider, region)
        return [HourlyCarbon(period=p, g_co2_per_kwh=g) for p, g in sorted(hourly.items())]
