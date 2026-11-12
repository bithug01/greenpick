"""Tokyo-area carbon from TEPCO's published area supply-and-demand results (エリア需給実績).

TEPCO publishes one CSV per month for the Tokyo area (area code 03), in Japan's national unified
format: 30-minute rows (JST), with generation by source in MW averaged over each half hour (thermal
split into LNG, coal, oil and other, plus nuclear, hydro, geothermal, biomass, solar and wind). The
current month's file is updated through the day, about an hour behind. No key is needed.

Used with permission from Tokyo Electric Power Company Holdings, Inc. (granted 10 November 2026, with the
attribution wording, the calculated figures and a link to the source page confirmed 11 November 2026), on
condition that TEPCO is credited as the source and its materials are not altered or edited. GreenPick
does neither show nor republish TEPCO's figures: it calculates an estimated carbon intensity from the
generation mix, weighted with GreenPick's own per-fuel factors (emission_factors.json ->
japan_fuel_to_factor), the same way the EIA, ENTSO-E and Canadian mixes are. Every result built on it
carries the attribution in ATTRIBUTION.

Production-based, like the other sources: pumped storage, batteries, interconnector imports (about a
tenth of Tokyo's supply) and the unclassified "other" column are left out. Requests are kept light:
each installation fetches the current month's file at most once every 30 minutes, also after a failed
attempt, and the previous month's file (needed only in the first days of a month) at most once a day.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .. import __version__
from ..models import CarbonReading, HourlyCarbon, Provider
from ._net import REQUEST_DEADLINE_S, REQUEST_TIMEOUT, describe_error
from .static_data import emission_factors, region_meta
from .typical_repository import TypicalCarbonRepository

log = logging.getLogger("greenpick.japan")

URL = "https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{yyyymm}_03.csv"
USER_AGENT = f"GreenPick/{__version__} (+https://github.com/bithug01/greenpick)"
ATTRIBUTION = ("Source: Tokyo Electric Power Company Holdings, Inc. Carbon intensity estimated by "
               "GreenPick from TEPCO's published area supply-and-demand data.")
LABEL = "TEPCO"

MIN_INTERVAL_S = 1800.0          # never fetch the current month's file more often than this
PREVIOUS_MONTH_TTL_S = 86400.0   # last month's file is final; refetch at most daily
MIN_HISTORY_HOURS = 48           # below this, also read the previous month (start of a month)
_JST = timezone(timedelta(hours=9))


def _factors() -> dict[str, float]:
    return emission_factors()["japan_fuel_to_factor"]["tepco"]


def month_key(dt: datetime) -> str:
    """The YYYYMM of a moment, in Japan time (the file names follow JST months)."""
    return dt.astimezone(_JST).strftime("%Y%m")


def previous_month_key(yyyymm: str) -> str:
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    return f"{y - 1}12" if m == 1 else f"{y}{m - 1:02d}"


def csv_to_hourly(text: str) -> dict[str, float]:
    """TEPCO area CSV text -> {UTC hour 'YYYY-MM-DDTHH': gCO2/kWh}.

    Each 30-minute JST row is a half-hour average in MW. The two half hours of each UTC hour are
    summed per fuel, then weighted, so the hour's intensity reflects its whole generation mix. Rows
    not yet published (empty demand) and hours with only one half filled in are skipped."""
    factors = _factors()
    rows = list(csv.reader(io.StringIO(text)))
    header_i = next((i for i, r in enumerate(rows) if r and r[0].strip() == "DATE"), None)
    if header_i is None:
        return {}
    col = {name.strip(): i for i, name in enumerate(rows[header_i])}
    if "TIME" not in col or not all(name in col for name in factors):
        return {}
    demand_i = 2
    mixes: dict[str, dict[str, float]] = {}
    halves: dict[str, int] = {}
    for r in rows[header_i + 1:]:
        if len(r) <= max(col.values()) or not r[demand_i].strip():
            continue                                  # not published yet
        try:
            start = datetime.strptime(f"{r[0].strip()} {r[col['TIME']].strip()}", "%Y/%m/%d %H:%M")
        except ValueError:
            continue
        period = start.replace(tzinfo=_JST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
        mix = mixes.setdefault(period, {})
        for name in factors:
            try:
                mw = float(r[col[name]] or 0)
            except ValueError:
                mw = 0.0
            if mw > 0:
                mix[name] = mix.get(name, 0.0) + mw
        halves[period] = halves.get(period, 0) + 1
    out: dict[str, float] = {}
    for period, mix in mixes.items():
        total = sum(mix.values())
        if halves[period] == 2 and total > 0:
            out[period] = round(sum(mw * factors[name] for name, mw in mix.items()) / total, 1)
    return out


def decode(content: bytes) -> str:
    """TEPCO's CSV is Shift-JIS (cp932); fall back to UTF-8 if that ever changes."""
    for enc in ("cp932", "utf-8-sig"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("cp932", errors="replace")


class JapanRepository:
    """Live Tokyo-area carbon (TEPCO), keyed off a region's jp_source."""

    def __init__(self, cache_ttl_seconds: int = 1800) -> None:
        # Never fetch more often than promised to TEPCO, even if a shorter cache TTL is configured.
        self._ttl = max(float(cache_ttl_seconds), MIN_INTERVAL_S)
        self._fallback = TypicalCarbonRepository()
        self._files: dict[str, tuple[float, dict[str, float]]] = {}   # yyyymm -> (fetched_at, hourly)
        self._last_attempt: dict[str, float] = {}                     # yyyymm -> time of last request

    async def _get_month(self, client: httpx.AsyncClient, yyyymm: str, ttl: float) -> Optional[dict[str, float]]:
        hit = self._files.get(yyyymm)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        if time.time() - self._last_attempt.get(yyyymm, 0.0) < ttl:
            return hit[1] if hit else None            # tried recently: don't ask again yet
        self._last_attempt[yyyymm] = time.time()
        try:
            resp = await asyncio.wait_for(client.get(URL.format(yyyymm=yyyymm)), timeout=REQUEST_DEADLINE_S)
            resp.raise_for_status()
            hourly = csv_to_hourly(decode(resp.content))
        except Exception as e:
            log.debug("%s fetch for %s failed (%s) — fallback", LABEL, yyyymm, describe_error(e))
            return hit[1] if hit else None
        if hourly:
            self._files[yyyymm] = (time.time(), hourly)
            return hourly
        return hit[1] if hit else None

    async def _fetch(self) -> Optional[dict[str, float]]:
        now = datetime.now(timezone.utc)
        current = month_key(now)
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            hourly = dict(await self._get_month(client, current, self._ttl) or {})
            if len(hourly) < MIN_HISTORY_HOURS:
                hourly.update(await self._get_month(client, previous_month_key(current), PREVIOUS_MONTH_TTL_S) or {})
        return hourly or None

    def _fresh(self) -> bool:
        """True if the current month's file was fetched within the last few seconds (a live read)."""
        hit = self._files.get(month_key(datetime.now(timezone.utc)))
        return bool(hit and time.time() - hit[0] < 5)

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        source = (region_meta(provider, region) or {}).get("jp_source")
        hourly = await self._fetch() if source == "tepco" else None
        if not hourly:
            return await self._fallback.carbon_now(provider, region)
        latest = max(hourly)
        return CarbonReading(region=region, provider=provider, g_co2_per_kwh=hourly[latest],
                             source="tepco", timestamp=latest,
                             quality="live" if self._fresh() else "cached")

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        source = (region_meta(provider, region) or {}).get("jp_source")
        hourly = await self._fetch() if source == "tepco" else None
        if not hourly:
            return await self._fallback.carbon_history(provider, region)
        return [HourlyCarbon(period=p, g_co2_per_kwh=g) for p, g in sorted(hourly.items())]
