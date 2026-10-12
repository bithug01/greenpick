"""Carbon-aware scheduling: when is a region cleanest to run a deferrable job?

Reuses the repository's recent hourly history. Pure logic over the returned series — the data
layer decides live-vs-mock and labels quality honestly. Directional, design-time advice
("set your nightly job to this hour"), not a scheduler.
"""
from __future__ import annotations

from ..models import SchedulingAdvice, Provider
from ..data.repository import CarbonRepository


async def cleanest_hours(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    top_n: int = 3,
) -> SchedulingAdvice:
    history = await repo.carbon_history(provider, region)
    # Derive source/quality from a current reading (history doesn't carry it).
    now = await repo.carbon_now(provider, region)

    if not history:
        return SchedulingAdvice(
            region=region, provider=provider, source=now.source, quality=now.quality,
            hours_analyzed=0, cleanest=[],
            note="No recent hourly history available for this region — can't advise on timing.",
        )

    ordered = sorted(history, key=lambda h: h.g_co2_per_kwh)
    cleanest = ordered[:max(1, top_n)]
    lo = ordered[0].g_co2_per_kwh
    hi = ordered[-1].g_co2_per_kwh
    reduction = round((hi - lo) / hi * 100, 1) if hi > 0 else None

    if reduction is not None and reduction >= 10:
        note = (f"Running during the cleanest hour instead of the dirtiest cuts this region's grid "
                f"carbon by ~{reduction:.0f}%. Good candidate for time-shifting deferrable work "
                f"(batch jobs, ETL, backups, training).")
    else:
        note = ("This region's grid carbon is fairly flat over the window — time-shifting here "
                "won't help much; focus on region choice instead.")

    return SchedulingAdvice(
        region=region, provider=provider, source=now.source, quality=now.quality,
        hours_analyzed=len(history), cleanest=cleanest,
        dirtiest_g_co2_per_kwh=hi, cleanest_g_co2_per_kwh=lo,
        potential_reduction_pct=reduction, note=note,
    )
