"""Typical carbon source — the fallback whenever live data isn't available.

Serves, for the current calendar month, a region's average grid carbon intensity and its average
24-hour profile (UTC), computed from 12 months of real hourly data (EIA-930 / ENTSO-E A75) by
scripts/refresh_typical.py and bundled as data/typical.json. Labelled quality="typical": real
data, but a monthly norm, not a current reading.

Regions the file doesn't cover (no free live source, e.g. Sydney) — or a month it lacks — fall
through to MockCarbonRepository's hand-set values, still labelled quality="mock".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models import CarbonReading, HourlyCarbon, Provider
from .mock_repository import MockCarbonRepository
from .static_data import typical


def typical_entry(provider: str, region: str) -> Optional[dict]:
    """The typical.json entry for a region (source, from, to, months), or None."""
    return typical().get("regions", {}).get(provider, {}).get(region)


def _month(entry: dict) -> Optional[dict]:
    return entry.get("months", {}).get(str(datetime.now(timezone.utc).month))


# Within this % of the typical value, a reading is "about usual" rather than cleaner/dirtier.
USUAL_BAND_PCT = 10.0


def _when(timestamp: str) -> datetime:
    """The UTC moment a reading refers to (EIA '2026-10-23T06', ISO with Z/offset); now if unparseable."""
    t = (timestamp or "").strip().replace("Z", "+00:00")
    for candidate in (t, t[:13]):
        try:
            dt = datetime.fromisoformat(candidate) if len(candidate) > 13 else \
                datetime.strptime(candidate, "%Y-%m-%dT%H")
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def typical_context(provider: str, region: str, g_co2_per_kwh: float, timestamp: str) -> Optional[dict]:
    """Compare a live reading with what's typical for that region, month and hour of day.
    None if the region has no typical data."""
    entry = typical_entry(provider, region)
    if not entry:
        return None
    when = _when(timestamp).astimezone(timezone.utc)
    month = entry.get("months", {}).get(str(when.month))
    if not month:
        return None
    hourly = month["hourly_utc"][when.hour]
    typical_now = hourly if hourly is not None else month["avg_g_co2_per_kwh"]
    pct = round((g_co2_per_kwh - typical_now) / typical_now * 100, 1) if typical_now else None
    if pct is None or abs(pct) < USUAL_BAND_PCT:
        verdict = "about_usual"
        words = "about usual"
    elif pct < 0:
        verdict, words = "cleaner_than_usual", f"~{abs(pct):.0f}% cleaner than usual"
    else:
        verdict, words = "dirtier_than_usual", f"~{pct:.0f}% dirtier than usual"
    month_name = when.strftime("%B")
    return {
        "typical_this_hour_g_co2_per_kwh": typical_now,
        "typical_month_avg_g_co2_per_kwh": month["avg_g_co2_per_kwh"],
        "vs_typical_pct": pct,
        "vs_typical": verdict,
        "typical_note": (f"Live {g_co2_per_kwh:.0f} gCO2/kWh is {words} for {when.hour:02d}:00 UTC in "
                         f"{month_name} (typical ~{typical_now:.0f}; {month_name} average "
                         f"~{month['avg_g_co2_per_kwh']:.0f}, from a year of {entry['source'].upper()} "
                         f"data). Directional context, not a forecast."),
    }


class TypicalCarbonRepository:
    def __init__(self) -> None:
        self._mock = MockCarbonRepository()

    async def carbon_now(self, provider: Provider, region: str) -> CarbonReading:
        entry = typical_entry(provider, region)
        month = _month(entry) if entry else None
        if not month:
            return await self._mock.carbon_now(provider, region)
        return CarbonReading(
            region=region,
            provider=provider,
            g_co2_per_kwh=month["avg_g_co2_per_kwh"],
            source=f"typical_{entry['source']}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            quality="typical",
        )

    async def carbon_history(self, provider: Provider, region: str) -> list[HourlyCarbon]:
        """This month's average day, hour by hour. Periods are 'H15Z' style: an hour of the day in
        UTC, not a date — it's a typical pattern, not a record of specific past hours."""
        entry = typical_entry(provider, region)
        month = _month(entry) if entry else None
        if not month:
            return await self._mock.carbon_history(provider, region)
        return [HourlyCarbon(period=f"H{h:02d}Z", g_co2_per_kwh=g)
                for h, g in enumerate(month["hourly_utc"]) if g is not None]
