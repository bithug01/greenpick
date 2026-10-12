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
import re
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


def _parse_interval_start(text: str) -> datetime | None:
    """ENTSO-E timestamps look like '2026-10-11T18:00Z' or '2026-10-11T18:00:00Z'.
    Parse to an aware UTC datetime; return None if unrecognisable."""
    if not text:
        return None
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _resolution_minutes(text: str) -> int:
    """Parse an ISO-8601 duration like 'PT60M' / 'PT15M' / 'PT1H' -> minutes.
    Defaults to 60 if absent/unrecognised (A75 realised data is typically hourly)."""
    if not text:
        return 60
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", text.strip())
    if not m:
        return 60
    hours = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    total = hours * 60 + mins
    return total or 60


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

        xml_text = await self._fetch_xml(eic, hours_back=3)
        if xml_text is None:
            return await self._fallback.carbon_now(provider, region)
        reading = self._xml_to_reading(provider, region, xml_text)
        if reading is None:
            return await self._fallback.carbon_now(provider, region)
        self._cache[eic] = (time.time(), reading)
        return reading

    async def _fetch_xml(self, eic: str, hours_back: int) -> str | None:
        """Fetch A75 realised-generation XML for an area over the last `hours_back` hours.
        Retries transient empties/errors; returns the body text, or None on auth failure or
        exhausted retries (callers fall back to mock). Shared by carbon_now and carbon_history."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=hours_back)
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
                    return None   # auth: don't retry
                resp.raise_for_status()
                if resp.text and "<TimeSeries" in resp.text:
                    return resp.text
                # 200 but no usable generation (transient empty) -> retry
                log.debug("ENTSO-E empty for %s (attempt %d/%d)", eic, attempt, attempts)
            except Exception as e:
                log.debug("ENTSO-E call failed for %s (attempt %d/%d): %s", eic, attempt, attempts, e)
            if attempt < attempts:
                await asyncio.sleep(0.6 * attempt)   # brief backoff: 0.6s, 1.2s
        return None

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """Recent hourly carbon intensity for an EU zone, for scheduling deferrable work.

        Parses A75 realised generation across the whole 24h window (every Point position,
        not just the latest), aligns all production types onto their hour, and weights each
        hour's fuel mix by emission factors. Falls back to the synthetic mock curve only when
        there's no token, no EIC, or the fetch/parse yields nothing usable."""
        meta = region_meta(provider, region) or {}
        eic = meta.get("entsoe_eic")
        if not self._token or not eic:
            return await self._fallback.carbon_history(provider, region)

        xml_text = await self._fetch_xml(eic, hours_back=24)
        if xml_text is None:
            return await self._fallback.carbon_history(provider, region)

        series = self._xml_to_hourly(xml_text)
        return series or await self._fallback.carbon_history(provider, region)

    def _xml_to_hourly(self, xml_text: str) -> list[HourlyCarbon]:
        """Parse A75 XML into an hourly carbon series.

        For each TimeSeries (one production type) we walk every Point, map its position to a
        timestamp (period start + (position-1) * resolution), and accumulate MW per fuel into
        the Point's hour bucket. Then per hour: weighted mean of fuels -> gCO2/kWh.
        Sub-hourly resolutions (e.g. PT15M) are summed into their containing hour."""
        factor_map = emission_factors()["entsoe_psrtype_to_factor"]
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # hour_iso -> {psrType -> summed MW}  (MW summed across sub-hour points & timeseries chunks)
        by_hour: dict[str, dict[str, float]] = {}

        for ts in root.iter():
            if _strip_ns(ts.tag) != "TimeSeries":
                continue
            psr = None
            for el in ts.iter():
                tag = _strip_ns(el.tag)
                if tag == "psrType" and el.text:
                    psr = el.text.strip()
                elif tag == "Period":
                    start_dt = None
                    resolution_min = 60
                    for c in el.iter():
                        ct = _strip_ns(c.tag)
                        if ct == "start" and c.text and start_dt is None:
                            start_dt = _parse_interval_start(c.text)
                        elif ct == "resolution" and c.text:
                            resolution_min = _resolution_minutes(c.text)
                    if start_dt is None or psr is None or psr not in factor_map:
                        continue
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
                        if pos is None or qty is None:
                            continue
                        point_dt = start_dt + timedelta(minutes=(pos - 1) * resolution_min)
                        hour_iso = point_dt.strftime("%Y-%m-%dT%H")
                        bucket = by_hour.setdefault(hour_iso, {})
                        bucket[psr] = bucket.get(psr, 0.0) + qty

        out: list[HourlyCarbon] = []
        for hour_iso in sorted(by_hour):
            fuels = by_hour[hour_iso]
            total = sum(fuels.values())
            if total <= 0:
                continue
            weighted = sum(mw * factor_map[f] for f, mw in fuels.items())
            out.append(HourlyCarbon(period=hour_iso, g_co2_per_kwh=round(weighted / total, 1)))
        return out

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
