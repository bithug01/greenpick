"""Carbon-aware scheduling: when is a region cleanest to run a deferrable job?

Reuses the repository's recent hourly history. Pure logic over the returned series — the data
layer decides live-vs-mock and labels quality honestly. Directional, design-time advice
("set your nightly job to this hour"), not a scheduler.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models import SchedulingAdvice, CleanestWindow, HourlyCarbon, Provider
from ..data.repository import CarbonRepository


def _hour_index(period: str) -> Optional[int]:
    """Map a period label to an absolute hour index so we can detect CONTIGUOUS runs.
    Handles ISO hours ('2026-10-12T18' / '2026-10-12T18:00') and mock labels ('H18').
    Returns None if unrecognised (such a point can't anchor a window)."""
    p = period.strip()
    if p.startswith("H") and p[1:].isdigit():
        return int(p[1:])                       # mock: H00..H23, already sequential
    iso = p if len(p) > 13 else p + ":00:00"    # '...T18' -> '...T18:00:00'
    iso = iso.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            dt = datetime.strptime(p[:13], "%Y-%m-%dT%H")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() // 3600)          # absolute hours since epoch


def _best_and_worst_window(series: list[HourlyCarbon], window_hours: int
                           ) -> tuple[Optional[list[HourlyCarbon]], Optional[float]]:
    """Slide a window of `window_hours` over the CHRONOLOGICALLY ordered series, considering only
    runs of genuinely consecutive hours (a gap breaks a window). Returns (best_window_hours,
    reduction_pct_best_vs_worst), or (None, None) if no contiguous run is long enough."""
    chrono = sorted(
        [(h, _hour_index(h.period)) for h in series if _hour_index(h.period) is not None],
        key=lambda t: t[1],  # type: ignore[arg-type]
    )
    best: Optional[tuple[float, list[HourlyCarbon]]] = None
    worst_avg: Optional[float] = None
    for i in range(len(chrono) - window_hours + 1):
        chunk = chrono[i:i + window_hours]
        # Contiguity: indices must step by exactly 1 across the whole chunk.
        idxs = [t[1] for t in chunk]
        if any(idxs[j + 1] - idxs[j] != 1 for j in range(len(idxs) - 1)):
            continue
        hours = [t[0] for t in chunk]
        avg = sum(h.g_co2_per_kwh for h in hours) / window_hours
        if best is None or avg < best[0]:
            best = (avg, hours)
        if worst_avg is None or avg > worst_avg:
            worst_avg = avg
    if best is None:
        return None, None
    reduction = (round((worst_avg - best[0]) / worst_avg * 100, 1)
                 if worst_avg and worst_avg > 0 else None)
    return best[1], reduction


async def cleanest_hours(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    top_n: int = 3,
    window_hours: Optional[int] = None,
) -> SchedulingAdvice:
    """Cleanest recent hours to run a deferrable job. If `window_hours` >= 2, also find the
    lowest-average CONTIGUOUS run of that many hours — the right question for a job of known
    duration (you can't start one job across scattered non-adjacent hours)."""
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

    advice = SchedulingAdvice(
        region=region, provider=provider, source=now.source, quality=now.quality,
        hours_analyzed=len(history), cleanest=cleanest,
        dirtiest_g_co2_per_kwh=hi, cleanest_g_co2_per_kwh=lo,
        potential_reduction_pct=reduction, note=note,
    )

    # Window mode: the cleanest contiguous run to START a job of this duration.
    if window_hours and window_hours >= 2:
        win_hours, win_reduction = _best_and_worst_window(history, window_hours)
        if win_hours:
            avg = round(sum(h.g_co2_per_kwh for h in win_hours) / len(win_hours), 1)
            advice.window = CleanestWindow(
                window_hours=window_hours,
                start_period=win_hours[0].period, end_period=win_hours[-1].period,
                avg_g_co2_per_kwh=avg, hours=win_hours,
            )
            advice.window_reduction_pct = win_reduction
            if win_reduction is not None and win_reduction >= 10:
                advice.note = (f"For a ~{window_hours}h job, start it at {win_hours[0].period}: that's "
                               f"the cleanest {window_hours}h window (avg ~{avg:.0f} gCO2/kWh), "
                               f"~{win_reduction:.0f}% cleaner than the worst {window_hours}h window.")
            else:
                advice.note = (f"For a ~{window_hours}h job, the cleanest window starts at "
                               f"{win_hours[0].period} (avg ~{avg:.0f} gCO2/kWh), but the grid is "
                               f"fairly flat — timing won't help much here.")
        else:
            advice.note = (f"Not enough contiguous history to find a {window_hours}h window; "
                           f"showing cleanest individual hours instead. " + advice.note)

    return advice
