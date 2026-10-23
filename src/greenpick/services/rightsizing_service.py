"""Right-sizing — the #1 FinOps finding, with a carbon twin.

Over-provisioning is the most common cloud waste: you pay for (and emit carbon for) capacity you
don't use. This is a PURE efficiency dual-benefit — dropping to a size that still fits your real
utilisation cuts BOTH the bill and the carbon, no tradeoff. GreenPick reuses its cost coefficients
and power model; the user/agent supplies observed utilisation (no billing-account access needed).

Design-time and directional: it's an estimate from the utilisation you report, not a reading of
your running fleet. We keep sensible headroom so the recommendation never under-provisions.
"""
from __future__ import annotations

from typing import Optional

from ..models import Workload, Provider, RightsizingAdvice
from ..data.repository import CarbonRepository
from . import carbon_service, cost_service

# Keep this much headroom above observed peak so we don't right-size into a cliff.
_HEADROOM = 1.4
# Don't recommend a change unless it saves at least this fraction — avoids noisy micro-advice.
_MIN_SAVING_PCT = 10.0


def _needed(provisioned: float, utilization: Optional[float]) -> float:
    """Capacity actually needed = observed usage x headroom. If utilisation is unknown, assume the
    dimension is needed in full (we only right-size what the user told us about)."""
    if utilization is None:
        return provisioned
    u = max(0.0, min(1.0, utilization))
    return provisioned * u * _HEADROOM


# Standard instance shapes shared by AWS / GCP / Azure: vCPU counts step in powers of two (plus the
# common 48/96/192), and memory comes at ~2 GB/vCPU (compute-optimised), ~4 GB/vCPU (general
# purpose) or ~8 GB/vCPU (memory-optimised). Recommending only these shapes means the answer is a
# size you can actually buy, and the saving is priced on that size — not on a fractional ideal.
_VCPU_SIZES = (1, 2, 4, 8, 16, 32, 48, 64, 96, 128, 192)
_GB_PER_VCPU = (2, 4, 8)


def _standard_size(need_vcpu: float, need_ram: float,
                   prov_vcpu: float, prov_ram: float) -> tuple[float, float]:
    """Smallest standard shape covering both needs, never larger than what's provisioned
    (right-sizing only shrinks or holds). Falls back to the provisioned size if nothing fits."""
    for v in _VCPU_SIZES:
        if v < need_vcpu or v > prov_vcpu:
            continue
        for ratio in _GB_PER_VCPU:
            ram = v * ratio
            if ram >= need_ram and ram <= prov_ram:
                return float(v), float(ram)
    return prov_vcpu, prov_ram


async def rightsizing_check(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    vcpu: float,
    ram_gb: float,
    cpu_utilization: float,
    ram_utilization: Optional[float] = None,
    hours_per_month: float = 730,
) -> RightsizingAdvice:
    rec_vcpu, rec_ram = _standard_size(
        _needed(vcpu, cpu_utilization), _needed(ram_gb, ram_utilization), vcpu, ram_gb,
    )

    now_wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=hours_per_month)
    rs_wl = Workload(vcpu=rec_vcpu, ram_gb=rec_ram, hours_per_month=hours_per_month)

    reading = await carbon_service.carbon_now(repo, provider, region)
    cost_now = cost_service.estimate_monthly_cost_usd(provider, now_wl)
    cost_rs = cost_service.estimate_monthly_cost_usd(provider, rs_wl)
    carbon_now = carbon_service.estimate_kg_co2_per_month(now_wl, reading)
    carbon_rs = carbon_service.estimate_kg_co2_per_month(rs_wl, reading)

    usd_saving = round(cost_now - cost_rs, 2) if (cost_now is not None and cost_rs is not None) else None
    kg_saving = round(carbon_now - carbon_rs, 2)
    saving_pct = (round((carbon_now - carbon_rs) / carbon_now * 100, 1)
                  if carbon_now > 0 else None)

    is_oversized = saving_pct is not None and saving_pct >= _MIN_SAVING_PCT

    if is_oversized:
        usd_txt = f"~${usd_saving:,.0f}/mo" if usd_saving is not None else "cost"
        rationale = (
            f"Over-provisioned: at ~{cpu_utilization*100:.0f}% CPU use, {vcpu:g} vCPU / {ram_gb:g} GB "
            f"is bigger than you need. Right-size to {rec_vcpu:g} vCPU / {rec_ram:g} GB (the smallest "
            f"standard size that keeps ~40% headroom) to cut ~{saving_pct:.0f}% - {usd_txt} AND "
            f"~{kg_saving:.1f} kg CO2/mo. "
            f"Same work, less waste: the cost and carbon win here are the same action.")
    else:
        rationale = (
            f"Already reasonably sized: at ~{cpu_utilization*100:.0f}% CPU use, {vcpu:g} vCPU / "
            f"{ram_gb:g} GB has sensible headroom. No material right-sizing saving (< "
            f"{_MIN_SAVING_PCT:.0f}%) — look to region choice or scheduling instead.")

    return RightsizingAdvice(
        provider=provider, region=region,
        provisioned_vcpu=vcpu, provisioned_ram_gb=ram_gb,
        observed_cpu_utilization=cpu_utilization, observed_ram_utilization=ram_utilization,
        recommended_vcpu=rec_vcpu, recommended_ram_gb=rec_ram, is_oversized=is_oversized,
        cost_now_usd_per_month=cost_now, cost_rightsized_usd_per_month=cost_rs,
        monthly_usd_saving=usd_saving,
        carbon_now_kg_per_month=carbon_now, carbon_rightsized_kg_per_month=carbon_rs,
        monthly_kg_co2_saving=kg_saving, saving_pct=saving_pct,
        carbon_source=reading.source, carbon_quality=reading.quality,
        rationale=rationale,
        limitations=("Directional, design-time estimate from the utilisation YOU report — not a "
                     "reading of your running fleet, and not a quote. Keeps ~40% headroom above "
                     "observed peak, rounded up to a standard shape (power-of-two vCPU at ~2/4/8 GB "
                     "per vCPU) — confirm your provider offers that size in the family you need; "
                     "validate against real load before resizing production. Cost "
                     "uses the dated static table; carbon = power model x live grid intensity."),
    )
