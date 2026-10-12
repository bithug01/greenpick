"""Assemble the tri-axis recommendation: carbon + cost + latency across candidate regions.

This is the heart of GreenPick's differentiation — not just "which region is cleanest",
but "cleanest within YOUR latency budget, and here's what it costs you".
"""
from __future__ import annotations

from ..models import (
    Workload, GeoPoint, Provider, RegionCandidate, Recommendation,
)
from ..data.repository import CarbonRepository
from ..data.static_data import iter_regions
from . import carbon_service, cost_service, latency_service

LIMITATIONS = (
    "Directional guidance, not audited accounting. Grid-zone mapping is approximate; "
    "carbon is point-in-time (not flow-traced consumption); cost is a ballpark, not a quote; "
    "latency is a geographic estimate. 'Greener' assumes grid intensity dominates and ignores "
    "embodied/hardware carbon and provider renewable-energy certificates."
)


def _candidate_providers(providers: list[Provider] | None) -> set[str]:
    return set(providers) if providers else {"aws", "gcp", "azure"}


async def compare_regions(
    repo: CarbonRepository,
    providers: list[Provider] | None,
    user_location: GeoPoint,
    workload: Workload,
    optimize_for: str = "carbon",       # "carbon" | "balanced"
    max_added_latency_ms: float | None = None,
    baseline_region: str | None = None,
) -> Recommendation:
    wanted = _candidate_providers(providers)

    candidates: list[RegionCandidate] = []
    for provider, region, _meta in iter_regions():
        if provider not in wanted:
            continue
        reading = await carbon_service.carbon_now(repo, provider, region)
        cand = RegionCandidate(
            region=region,
            provider=provider,  # type: ignore[arg-type]
            carbon=reading,
            est_monthly_cost_usd=cost_service.estimate_monthly_cost_usd(provider, workload),  # type: ignore[arg-type]
            latency_ms_estimate=latency_service.estimate_latency_ms(provider, region, user_location),  # type: ignore[arg-type]
        )
        candidates.append(cand)

    if not candidates:
        return Recommendation(candidates=[], rationale="No known regions matched the request.",
                              limitations=LIMITATIONS)

    # Carbon ranking across the candidate set.
    ordered = sorted(candidates, key=lambda c: c.carbon.g_co2_per_kwh)
    for i, c in enumerate(ordered, start=1):
        c.carbon_rank = i

    # Baseline selection:
    #  - explicit baseline_region if the caller gave one (their current region), else
    #  - the region NEAREST the user (lowest estimated latency) — the implicit "where I'd
    #    deploy by default". (Previously fell back to the DIRTIEST region, which produced
    #    confusing "cleaner than <a region I didn't ask about>; -272ms" tradeoff lines.)
    baseline = next((c for c in candidates if c.region == baseline_region), None)
    if baseline is None:
        with_latency = [c for c in candidates if c.latency_ms_estimate is not None]
        baseline = (min(with_latency, key=lambda c: c.latency_ms_estimate)  # type: ignore[arg-type]
                    if with_latency else ordered[-1])

    for c in candidates:
        if baseline.carbon.g_co2_per_kwh > 0:
            c.carbon_vs_baseline_pct = round(
                (c.carbon.g_co2_per_kwh - baseline.carbon.g_co2_per_kwh)
                / baseline.carbon.g_co2_per_kwh * 100, 1
            )
        if c.latency_ms_estimate is not None and baseline.latency_ms_estimate is not None:
            c.added_latency_ms = round(c.latency_ms_estimate - baseline.latency_ms_estimate, 1)
        c.tradeoff = _tradeoff_sentence(c, baseline)

    # Latency budget with a tolerance band: a strict "+100ms" that excludes +105ms feels
    # absurd to a user. Treat the cap as "~", allowing the larger of +15ms or +10% slack.
    def within_budget(c: RegionCandidate) -> bool:
        if max_added_latency_ms is None or c.added_latency_ms is None:
            return True
        slack = max(15.0, max_added_latency_ms * 0.10)
        return c.added_latency_ms <= max_added_latency_ms + slack

    eligible = [c for c in ordered if within_budget(c)]
    pick = (eligible[0] if eligible else ordered[0])

    # "No meaningful improvement" handling: if the best in-budget pick isn't materially
    # cleaner than the baseline (>=5%), don't dress up the baseline as a win — say staying
    # put is reasonable and surface what the greener options would cost.
    MEANINGFUL_PCT = 5.0
    pick_improvement = -(pick.carbon_vs_baseline_pct or 0.0)  # positive = cleaner than baseline
    is_baseline_pick = (pick.region == baseline.region and pick.provider == baseline.provider)

    if is_baseline_pick or pick_improvement < MEANINGFUL_PCT:
        # Find the greenest option overall (ignoring budget) to describe the tradeoff on offer.
        greenest = ordered[0]
        greener_improvement = -(greenest.carbon_vs_baseline_pct or 0.0)
        if greener_improvement < MEANINGFUL_PCT:
            rationale = (
                f"Staying on {baseline.provider}/{baseline.region} is reasonable — no candidate "
                f"region is meaningfully greener (all within ~{MEANINGFUL_PCT:.0f}%)."
            )
        else:
            extra_lat = greenest.added_latency_ms
            lat_txt = (f", but it adds ~{extra_lat:.0f}ms latency" if extra_lat and extra_lat > 0 else "")
            rationale = (
                f"Within your latency budget, {baseline.provider}/{baseline.region} is about as "
                f"good as it gets — nothing meaningfully greener fits. The greenest option overall "
                f"is {greenest.provider}/{greenest.region} (~{greener_improvement:.0f}% cleaner{lat_txt}); "
                f"widen the latency budget to reach it."
            )
        recommended = f"{baseline.provider}/{baseline.region}"
    else:
        budget_txt = ""
        if max_added_latency_ms is not None:
            budget_txt = f" within ~{max_added_latency_ms:.0f}ms added latency"
        rationale = (
            f"{pick.provider}/{pick.region} is ~{pick_improvement:.0f}% cleaner than "
            f"{baseline.provider}/{baseline.region}{budget_txt} "
            f"({pick.carbon.g_co2_per_kwh:.0f} gCO2/kWh, source={pick.carbon.source}, "
            f"quality={pick.carbon.quality})."
        )
        recommended = f"{pick.provider}/{pick.region}"

    return Recommendation(
        candidates=sorted(candidates, key=lambda c: c.carbon_rank or 999),
        recommended_region=recommended,
        rationale=rationale,
        limitations=LIMITATIONS,
    )


def _tradeoff_sentence(c: RegionCandidate, baseline: RegionCandidate) -> str:
    parts: list[str] = []
    if c.carbon_vs_baseline_pct is not None and c.region != baseline.region:
        if c.carbon_vs_baseline_pct < 0:
            parts.append(f"~{abs(c.carbon_vs_baseline_pct):.0f}% cleaner than {baseline.region}")
        elif c.carbon_vs_baseline_pct > 0:
            parts.append(f"~{c.carbon_vs_baseline_pct:.0f}% dirtier than {baseline.region}")
        else:
            parts.append(f"same carbon as {baseline.region}")
    if c.added_latency_ms is not None and c.region != baseline.region:
        sign = "+" if c.added_latency_ms >= 0 else ""
        parts.append(f"{sign}{c.added_latency_ms:.0f}ms latency")
    if c.est_monthly_cost_usd is not None:
        parts.append(f"~${c.est_monthly_cost_usd:.0f}/mo")
    return "; ".join(parts) if parts else "baseline"
