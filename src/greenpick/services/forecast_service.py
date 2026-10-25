"""Forward-looking carbon-aware scheduling: which UPCOMING hours will be cleanest?

Turns scheduling from reactive (recent history) to planned (day-ahead). The honest signal — per
the data spike — is the ENTSO-E day-ahead wind+solar forecast (A69), reliable across EU zones.
We rank upcoming hours by forecast renewable output: more wind+solar = cleaner hour. This is a
RELATIVE ranking, not a gCO2/kWh forecast (the free data can't support absolute intensity ahead).

Degrade path: no forecast for the region (US today, or a zone ENTSO-E has no A69 for) -> fall back
to the recent historical daily pattern we already compute, relabelled 'historical' so the user
knows it's backward-looking, not a true forecast.
"""
from __future__ import annotations

from typing import Optional

from ..models import ForecastAdvice, ForecastHour, Provider
from ..data.repository import CarbonRepository
from . import scheduling_service

LIMITATIONS = (
    "RELATIVE forecast: upcoming hours ranked by day-ahead wind+solar output (more renewables = "
    "cleaner), NOT an absolute gCO2/kWh forecast — the free day-ahead data has no forecast fuel mix "
    "across all zones. EU only (ENTSO-E A69); US and uncovered zones degrade to the recent historical "
    "pattern (labelled 'historical'). Directional; forecasts shift with weather."
)


async def carbon_forecast(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    hours_ahead: int = 24,
    top_n: int = 5,
) -> ForecastAdvice:
    forecast: list[ForecastHour] = []
    getter = getattr(repo, "renewable_forecast", None)
    if getter is not None:
        forecast = await getter(provider, region, hours_ahead)

    if forecast:
        # Cleaner = MORE forecast renewable output. Rank descending by renewable_mw (or share if
        # every hour has it, which is a better normaliser).
        use_share = all(h.renewable_share is not None for h in forecast)
        key = (lambda h: h.renewable_share) if use_share else (lambda h: h.renewable_mw)
        by_clean = sorted(forecast, key=key, reverse=True)  # type: ignore[arg-type,return-value]
        peak = by_clean[0]
        low = by_clean[-1]
        metric = "renewable share" if use_share else "forecast wind+solar"
        note = (f"Over the next ~{hours_ahead}h, the grid in {provider}/{region} is forecast "
                f"cleanest around {peak.period} (highest {metric}) and dirtiest around "
                f"{low.period}. Shift deferrable work toward the cleanest upcoming hours.")
        return ForecastAdvice(
            region=region, provider=provider, source="entsoe_forecast", quality="forecast",
            hours_ahead=hours_ahead, cleanest_upcoming=by_clean[:max(1, top_n)],
            peak_renewable_period=peak.period, low_renewable_period=low.period,
            note=note, limitations=LIMITATIONS,
        )

    # --- Degrade: no forward forecast for this region -> recent historical daily pattern ---
    pattern = await scheduling_service.cleanest_time_of_day(repo, provider, region)
    if pattern.quality == "mock":
        # No live history either: the "pattern" is GreenPick's illustrative mock curve. Label it
        # mock — calling it 'historical' would pass a synthetic shape off as real past data.
        source, quality = "mock", "mock"
        note = ("No day-ahead forecast or live history is available for this region, so there's "
                "no real timing signal here. ")
        if pattern.cleanest_hour_of_day is not None:
            note += (f"GreenPick's illustrative mock pattern is cleanest around "
                     f"{pattern.cleanest_hour_of_day:02d}:00, but that's not meaningful for scheduling.")
    else:
        source, quality = "historical_fallback", "historical"
        note = ("No day-ahead forecast available for this region, so this is the recent HISTORICAL "
                "pattern, not a true forecast. ")
        if pattern.cleanest_hour_of_day is not None:
            note += (f"Over the last ~{pattern.days_analyzed} day(s) it's been cleanest around "
                     f"{pattern.cleanest_hour_of_day:02d}:00 UTC - a reasonable default for a "
                     f"recurring job.")
        else:
            note += "No usable recent history either."
    return ForecastAdvice(
        region=region, provider=provider, source=source, quality=quality,
        hours_ahead=hours_ahead, cleanest_upcoming=[],
        note=note, limitations=LIMITATIONS,
    )
