"""Greener instance-family suggestion.

The honest carbon mechanism here is performance-per-watt: a newer-generation or ARM
(Graviton-class) family does the SAME work on less energy, so for a fixed grid intensity it
emits less CO2. We take the user's current general-purpose family, look up directional
energy multipliers for the same-size families in that cloud, and rank the greener options —
reporting the energy saving, the CO2 estimate (energy x the region's live grid intensity),
and a relative R/Y/G rating.

Deliberately NOT a pricing engine: we don't claim per-family prices we don't have. Cost is
left to the region/cost tools; this tool's axis is energy -> carbon.
"""
from __future__ import annotations

from typing import Optional

from ..models import (
    Workload, Provider, CarbonReading,
    GreenerComputeAdvice, FamilyOption,
)
from ..data.repository import CarbonRepository
from ..data.static_data import power_model, instance_families
from . import carbon_service


SUPPORTED_PROVIDERS = ("aws", "gcp", "azure")


def is_supported_provider(provider: str) -> bool:
    return provider in SUPPORTED_PROVIDERS


def _families_for(provider: str) -> list[dict]:
    data = instance_families().get(provider, {})
    return list(data.get("_general_purpose_generations", []))


def _base_kwh_per_month(workload: Workload) -> float:
    """Energy for the baseline (relative_energy = 1.00) family — same power model the
    carbon estimate uses. Each family then scales this by its relative_energy."""
    pm = power_model()
    watts = (workload.vcpu * pm["watts_per_vcpu"] + workload.ram_gb * pm["watts_per_gb_ram"])
    watts *= pm["pue_default"]
    return watts / 1000.0 * workload.hours_per_month


def _rate(options: list[FamilyOption]) -> None:
    """Assign relative R/Y/G by energy terciles across the option set (greenest = green)."""
    if not options:
        return
    ordered = sorted(options, key=lambda o: o.relative_energy)
    n = len(ordered)
    for i, opt in enumerate(ordered):
        if n <= 2:
            opt.rating = "green" if i == 0 else ("red" if i == n - 1 else "yellow")
        else:
            third = n / 3.0
            opt.rating = "green" if i < third else ("red" if i >= 2 * third else "yellow")


async def greener_instance_family(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    vcpu: float,
    ram_gb: float,
    current_family: Optional[str] = None,
    hours_per_month: float = 730,
) -> GreenerComputeAdvice:
    families = _families_for(provider)
    if not families:
        return GreenerComputeAdvice(
            provider=provider, region=region, current_family=current_family,
            rationale=f"No instance-family efficiency data for provider '{provider}'.",
            limitations="Supported providers: aws, gcp, azure (general-purpose families only).",
        )

    reading: CarbonReading = await carbon_service.carbon_now(repo, provider, region)
    wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=hours_per_month)
    base_kwh = _base_kwh_per_month(wl)

    # Resolve the current family (case-insensitive); if unknown/omitted, compare against the
    # LEAST efficient family so savings are framed conservatively ("at least this much").
    by_name = {f["family"].lower(): f for f in families}
    current = by_name.get((current_family or "").lower())
    current_rel = current["relative_energy"] if current else max(f["relative_energy"] for f in families)
    current_resolved = current["family"] if current else None

    options: list[FamilyOption] = []
    for f in families:
        rel = f["relative_energy"]
        kwh = base_kwh * rel
        kg = round(kwh * reading.g_co2_per_kwh / 1000.0, 2)
        energy_saving = round((current_rel - rel) / current_rel * 100, 1) if current_rel > 0 else None
        co2_saving = energy_saving  # same grid intensity, so CO2 scales with energy
        options.append(FamilyOption(
            family=f["family"], arch=f["arch"], cpu=f["cpu"],
            relative_energy=rel,
            energy_saving_vs_current_pct=energy_saving,
            est_kg_co2_per_month=kg,
            co2_saving_vs_current_pct=co2_saving,
            note=f.get("notes", ""),
        ))

    options.sort(key=lambda o: o.relative_energy)   # greenest first
    _rate(options)
    greenest = options[0]

    # Rationale: honest about the mechanism and the ARM caveat.
    if current_resolved and greenest.family.lower() == current_resolved.lower():
        rationale = (f"You're already on {current_resolved}, the greenest general-purpose family "
                     f"available here. No change needed.")
    else:
        saving = greenest.energy_saving_vs_current_pct
        arm_note = (" It's an ARM (Graviton-class) family, so this assumes your workload can run "
                    "on ARM - a recompile/container rebuild may be needed."
                    if greenest.arch == "arm" else "")
        base = (f"vs {current_resolved}" if current_resolved
                else "vs the least-efficient family here")
        rationale = (f"{greenest.family} ({greenest.cpu}) does the same work on "
                     f"~{saving:.0f}% less energy {base}, so ~{saving:.0f}% less CO2 at this "
                     f"region's grid intensity.{arm_note}")

    return GreenerComputeAdvice(
        provider=provider, region=region, current_family=current_resolved,
        grid_intensity_g_co2_per_kwh=reading.g_co2_per_kwh,
        carbon_source=reading.source, carbon_quality=reading.quality,
        options=options, recommended_family=greenest.family, rationale=rationale,
        limitations=("Energy multipliers are DIRECTIONAL (perf-per-watt by generation/arch), "
                     "not measured for your workload; general-purpose families only; embodied "
                     "hardware carbon ignored. ARM options require ARM-compatible builds."),
    )
