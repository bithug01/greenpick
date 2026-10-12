"""ENTSO-E Transparency Platform carbon source (EU zones).

Free EU grid data. We query A75 (Actual Generation per Production Type) for a region's
area (EIC code), take the most recent period's MW per production type, and weight by
per-fuel emission factors -> directional gCO2/kWh. Mirrors the EIA source for the EU.

Token (free): register at https://transparency.entsoe.eu/ then request API access
(email transparency@entsoe.eu per their docs) -> security token.
Endpoint: GET https://web-api.tp.entsoe.eu/api
  params: securityToken, documentType=A75, processType=A16 (realised),
          in_Domain=<area EIC>, periodStart/periodEnd = YYYYMMDDHHMM (UTC)
Response: XML with <TimeSeries> per production type:
  <MktPSRType><psrType>B04</psrType></MktPSRType> and <Period><Point><quantity> MW.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import httpx

from ..models import CarbonReading, Provider, HourlyCarbon
from .mock_repository import MockCarbonRepository
from .static_data import region_meta, emission_factors

log = logging.getLogger("greenpick.entsoe")

_URL = "https://web-api.tp.entsoe.eu/api"


def _strip_ns(tag: str) -> str:
    """ENTSO-E XML is namespaced; strip '{ns}tag' -> 'tag' for simple matching."""
    return tag.rsplit("}", 1)[-1]


class ENTSOERepository:
    def __init__(self, token: str, cache_ttl_seconds: int = 1800) -> None:
        self._token = token
        self._ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, CarbonReading]] = {}  # EIC -> (fetched_at, reading)
        self._fallback = MockCarbonRepository()
        self._warned_no_token = False

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        meta = region_meta(provider, region) or {}
        eic = meta.get("entsoe_eic")

        if not self._token:
            if not self._warned_no_token:
                log.warning("No ENTSOE_TOKEN set — falling back to mock. Register at "
                            "https://transparency.entsoe.eu/ and request API access.")
                self._warned_no_token = True
            return await self._fallback.carbon_now(provider, region)
        if not eic:
            # Non-EU region (no ENTSO-E area) -> mock, labelled.
            return await self._fallback.carbon_now(provider, region)

        hit = self._cache.get(eic)
        if hit and (time.time() - hit[0]) < self._ttl:
            cached = hit[1]
            return cached.model_copy(update={"region": region, "provider": provider, "quality": "cached"})

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)   # a few hours back to ensure data exists
        params = {
            "securityToken": self._token,
            "documentType": "A75",
            "processType": "A16",
            "in_Domain": eic,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": now.strftime("%Y%m%d%H%M"),
        }

        # ENTSO-E is occasionally slow / empty for a given zone (their docs warn about response
        # times). Retry a couple of times before degrading to mock, since a transient miss would
        # otherwise show a region as mock for the whole cache window.
        import asyncio
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(_URL, params=params)
                if resp.status_code in (401, 403):
                    log.warning("ENTSO-E rejected the token (HTTP %s) — using mock. Check ENTSOE_TOKEN.",
                                resp.status_code)
                    return await self._fallback.carbon_now(provider, region)   # auth: don't retry
                resp.raise_for_status()
                reading = self._xml_to_reading(provider, region, resp.text)
                if reading is not None:
                    self._cache[eic] = (time.time(), reading)
                    return reading
                # 200 but no usable generation (transient empty) -> retry
                log.debug("ENTSO-E empty/unparseable for %s (attempt %d/%d)", eic, attempt, attempts)
            except Exception as e:
                log.debug("ENTSO-E call failed for %s (attempt %d/%d): %s", eic, attempt, attempts, e)
            if attempt < attempts:
                await asyncio.sleep(0.6 * attempt)   # brief backoff: 0.6s, 1.2s

        return await self._fallback.carbon_now(provider, region)

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """v1: ENTSO-E A75 multi-hour parsing isn't implemented yet; degrade to the synthetic
        fallback curve (honestly a placeholder) rather than block scheduling for EU regions.
        TODO: parse per-position Points across the Period for a real EU hourly series."""
        return await self._fallback.carbon_history(provider, region)

    def _xml_to_reading(self, provider: Provider, region: str, xml_text: str) -> CarbonReading | None:
        """Parse A75 XML: for each TimeSeries (one production type), take its latest
        Point quantity; weight all types by emission factors -> gCO2/kWh."""
        factor_map = emission_factors()["entsoe_psrtype_to_factor"]
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        gen_by_fuel: dict[str, float] = {}   # psrType -> latest MW
        latest_ts = ""

        for ts in root.iter():
            if _strip_ns(ts.tag) != "TimeSeries":
                continue
            psr = None
            latest_qty = None
            latest_pos_time = ""
            for el in ts.iter():
                tag = _strip_ns(el.tag)
                if tag == "psrType" and el.text:
                    psr = el.text.strip()
                elif tag == "Period":
                    # find the newest Point in this period by its 'position'
                    start_el = next((c for c in el.iter() if _strip_ns(c.tag) == "start"), None)
                    pstart = start_el.text if start_el is not None else ""
                    best_pos = -1
                    for pt in el.iter():
                        if _strip_ns(pt.tag) != "Point":
                            continue
                        pos = qty = None
                        for c in pt:
                            ct = _strip_ns(c.tag)
                            if ct == "position" and c.text:
                                pos = int(c.text)
                            elif ct == "quantity" and c.text:
                                qty = float(c.text)
                        if pos is not None and qty is not None and pos > best_pos:
                            best_pos, latest_qty, latest_pos_time = pos, qty, pstart or ""
            if psr and latest_qty is not None and psr in factor_map:
                # Keep the max across time series chunks (latest known MW for that fuel).
                gen_by_fuel[psr] = max(gen_by_fuel.get(psr, 0.0), latest_qty)
                latest_ts = latest_ts or latest_pos_time

        total = sum(gen_by_fuel.values())
        if total <= 0:
            return None
        weighted = sum(mw * factor_map[f] for f, mw in gen_by_fuel.items())
        return CarbonReading(
            region=region,
            provider=provider,
            g_co2_per_kwh=round(weighted / total, 1),
            source="entsoe",
            timestamp=latest_ts or datetime.now(timezone.utc).isoformat(),
            quality="live",
        )
