"""GPU training carbon: how much CO2 a training run emits, and the greener WHERE + WHEN.

Training is the workload where GreenPick's two best levers compound: a run is both PORTABLE
(pick the region) and DEFERRABLE (pick the hours). Unlike the always-on web service, a run is a
FIXED batch of work (~N GPU-hours, once), so we can place it in space and time.

Energy comes from the directional GPU power table (TDP x utilization + host overhead, x PUE);
carbon = energy x the region's LIVE grid intensity. Placement ranks regions greener-first; timing
reuses the carbon-aware scheduling service for the chosen (or greenest) region.

Honesty posture: energy is directional (TDP is peak, not a measurement of your run); region GPU
availability is NOT modelled — we flag it as something to verify, rather than maintain a matrix
that rots. Spot/on-demand, checkpointing, and multi-node networking are out of scope (orchestration,
not placement/timing).
"""
from __future__ import annotations

from typing import Optional

from ..models import (
    Provider, TrainingCarbonAdvice, TrainingRegionOption, HourlyCarbon,
)
from ..data.repository import CarbonRepository
from ..data.static_data import gpu_power, resolve_gpu, power_model, iter_regions
from . import carbon_service, scheduling_service, residency_service


def run_energy_kwh(gpu_key: str, gpu_count: int, gpu_hours: float,
                   utilization: float) -> float:
    """Directional energy for a run. gpu_hours is TOTAL accelerator-hours across all GPUs
    (e.g. 2 GPUs for 20h = 40 GPU-hours). Energy is independent of how it's split, since
    both the GPU draw and host overhead are per-accelerator."""
    gp = gpu_power()
    _key, spec = resolve_gpu(gpu_key)  # caller guarantees resolvable
    tdp = spec["tdp_watts"]
    host = gp["host_overhead_watts_per_gpu"]
    pue = power_model()["pue_default"]
    watts_per_gpu = tdp * utilization + host
    # gpu_hours is total accelerator-hours, so multiply watts-per-gpu by total gpu-hours directly.
    return watts_per_gpu / 1000.0 * gpu_hours * pue


def _rate(options: list[TrainingRegionOption]) -> None:
    """Relative R/Y/G by carbon terciles across the option set (greenest = green)."""
    if not options:
        return
    ordered = sorted(options, key=lambda o: o.est_kg_co2)
    n = len(ordered)
    for i, opt in enumerate(ordered):
        frac = i / n
        opt.rating = "green" if frac < 1/3 else "yellow" if frac < 2/3 else "red"


LIMITATIONS = (
    "Energy is DIRECTIONAL: published GPU TDP (peak, not your run's measured draw) x a utilization "
    "assumption + host overhead x PUE. Carbon = energy x the region's grid intensity. GPU AVAILABILITY "
    "per region is NOT checked — verify the card you need is offered there. Ignores spot/on-demand, "
    "checkpointing, multi-node networking, and embodied hardware carbon. Training datasets are often "
    "large and may live in another region: shipping them to the greenest region can incur significant "
    "EGRESS cost and transfer carbon — run data_locality_egress_check before moving the job."
)


async def estimate_training_carbon(
    repo: CarbonRepository,
    gpu: str,
    gpu_count: int,
    gpu_hours: float,
    region: Optional[str] = None,
    provider: Optional[Provider] = None,
    utilization: Optional[float] = None,
    top_n_regions: int = 5,
) -> TrainingCarbonAdvice:
    gp = gpu_power()
    resolved = resolve_gpu(gpu)
    util = utilization if utilization is not None else gp["default_utilization"]

    if resolved is None:
        known = ", ".join(gp["gpus"].keys())
        return TrainingCarbonAdvice(
            gpu=gpu, gpu_name=gpu, gpu_count=gpu_count, gpu_hours=gpu_hours,
            utilization=util, est_energy_kwh=0.0,
            rationale=f"Unknown GPU '{gpu}'. Known: {known}.",
            limitations=LIMITATIONS,
        )

    gpu_key, spec = resolved
    energy = round(run_energy_kwh(gpu_key, gpu_count, gpu_hours, util), 2)

    base = TrainingCarbonAdvice(
        gpu=gpu_key, gpu_name=spec["name"], gpu_count=gpu_count, gpu_hours=gpu_hours,
        # Echo the run's duration so callers report it rather than re-deriving it (a common slip
        # is reading gpu_hours as per-GPU and multiplying by gpu_count again).
        wall_clock_hours=round(gpu_hours / max(1, gpu_count), 1),
        utilization=util, est_energy_kwh=energy, limitations=LIMITATIONS,
    )

    # --- Placement: a specific region, or rank the catalog greener-first ---
    if region is not None:
        prov = provider or _guess_provider(region)
        if prov is None:
            base.rationale = (f"Region '{region}' not found. Pass provider= explicitly, or omit "
                              f"region to rank all regions.")
            return base
        reading = await carbon_service.carbon_now(repo, prov, region)
        kg = round(energy * reading.g_co2_per_kwh / 1000.0, 2)
        base.region = region
        base.recommended_region = f"{prov}/{region}"
        base.options = [TrainingRegionOption(
            provider=prov, region=region, grid_intensity_g_co2_per_kwh=reading.g_co2_per_kwh,
            carbon_source=reading.source, carbon_quality=reading.quality, est_kg_co2=kg,
            rating="green",
        )]
        chosen_prov, chosen_region = prov, region
        place_txt = (f"This run is ~{energy:.0f} kWh. In {prov}/{region} that's ~{kg:.1f} kg CO2 "
                     f"at {reading.g_co2_per_kwh:.0f} gCO2/kWh ({reading.source}, {reading.quality}).")
    else:
        wanted = {provider} if provider else {"aws", "gcp", "azure"}
        targets = [(prov, reg) for prov, reg, _meta in iter_regions() if prov in wanted]
        # Fetch all regions' carbon CONCURRENTLY — live sources (esp. ENTSO-E with retries) are
        # slow serially, and ranking needs every region before it can sort.
        import asyncio
        readings = await asyncio.gather(
            *(carbon_service.carbon_now(repo, prov, reg) for prov, reg in targets)  # type: ignore[arg-type]
        )
        options: list[TrainingRegionOption] = []
        for (prov, reg), reading in zip(targets, readings):
            kg = round(energy * reading.g_co2_per_kwh / 1000.0, 2)
            options.append(TrainingRegionOption(
                provider=prov, region=reg,  # type: ignore[arg-type]
                grid_intensity_g_co2_per_kwh=reading.g_co2_per_kwh,
                carbon_source=reading.source, carbon_quality=reading.quality, est_kg_co2=kg,
            ))
        if not options:
            base.rationale = "No known regions matched the request."
            return base
        options.sort(key=lambda o: o.est_kg_co2)   # greenest first
        greenest = options[0]
        dirtiest = options[-1]
        # vs_baseline computed against the FULL set's dirtiest (the real worst case), so the
        # headline "X% less than the dirtiest" reflects every region, not just the shown slice.
        for o in options:
            if dirtiest.est_kg_co2 > 0:
                o.vs_baseline_pct = round((o.est_kg_co2 - dirtiest.est_kg_co2) / dirtiest.est_kg_co2 * 100, 1)
        shown = options[:max(1, top_n_regions)]
        _rate(shown)   # R/Y/G relative to what's actually displayed
        base.options = shown
        base.recommended_region = f"{greenest.provider}/{greenest.region}"
        chosen_prov, chosen_region = greenest.provider, greenest.region
        saved_pct = abs(greenest.vs_baseline_pct) if greenest.vs_baseline_pct else 0.0
        place_txt = (f"This run is ~{energy:.0f} kWh. Greenest option is {greenest.provider}/"
                     f"{greenest.region} at ~{greenest.est_kg_co2:.1f} kg CO2 - ~{saved_pct:.0f}% "
                     f"less than the dirtiest option ({dirtiest.provider}/{dirtiest.region}, "
                     f"~{dirtiest.est_kg_co2:.1f} kg).")

    # --- Timing: reuse carbon-aware scheduling for the chosen/greenest region ---
    # A run's wall-clock duration ~= total GPU-hours / GPUs running in parallel. If that's >= 2h,
    # ask for the cleanest CONTIGUOUS window of that length (you start one job once), not scattered
    # hours. Cap at 24 so it stays within the history window.
    wall_clock_h = int(round(gpu_hours / max(1, gpu_count)))
    window = wall_clock_h if 2 <= wall_clock_h <= 24 else None
    advice = await scheduling_service.cleanest_hours(
        repo, chosen_prov, chosen_region, top_n=3, window_hours=window,
    )
    base.cleanest_hours = advice.cleanest
    base.cleanest_window = advice.window
    base.timing_reduction_pct = advice.potential_reduction_pct
    base.timing_source = advice.source
    base.timing_quality = advice.quality

    if advice.window and advice.window_reduction_pct and advice.window_reduction_pct >= 10:
        w = advice.window
        time_txt = (f" It runs ~{wall_clock_h}h wall-clock; start it around "
                    f"{scheduling_service.clock_label(w.start_period)} (the cleanest {w.window_hours}h "
                    f"window in the recent data began {w.start_period}, avg ~{w.avg_g_co2_per_kwh:.0f} "
                    f"gCO2/kWh), ~{advice.window_reduction_pct:.0f}% cleaner than the worst same-length "
                    f"window - training is deferrable, so this stacks on the region choice. "
                    f"A recent pattern, not a forecast.")
    elif advice.potential_reduction_pct and advice.potential_reduction_pct >= 10 and advice.cleanest:
        best = scheduling_service.clock_label(advice.cleanest[0].period)
        time_txt = (f" Timing it to the cleanest hours in that region (around {best}) cuts a further "
                    f"~{advice.potential_reduction_pct:.0f}% vs the dirtiest hour - training is "
                    f"deferrable, so this stacks on the region choice.")
    else:
        time_txt = (" That region's grid is fairly flat over the window, so when you run matters "
                    "little there — the region choice is the lever.")

    base.rationale = place_txt + time_txt

    # Residency context: training usually means shipping a dataset INTO the recommended region.
    # We don't know where the data lives, so we state the recommended region's jurisdiction as a
    # neutral heads-up (not a verdict) — most pointed when it's inside the EEA.
    jur = residency_service.jurisdiction_of(chosen_prov, chosen_region)
    if jur:
        where = residency_service._LABEL.get(jur, jur)
        if jur == "EEA":
            base.residency_note = (
                f"RESIDENCY: the recommended region ({chosen_prov}/{chosen_region}) is in {where}. "
                f"Shipping a training dataset in or out of the EEA can trigger GDPR transfer rules "
                f"if it contains personal data. {residency_service.DISCLAIMER}")
        else:
            base.residency_note = (
                f"RESIDENCY: the recommended region ({chosen_prov}/{chosen_region}) is in {where}. "
                f"If your training data lives in another jurisdiction, moving it here may trigger "
                f"residency rules. {residency_service.DISCLAIMER}")
    return base


def _guess_provider(region: str) -> Optional[str]:
    """Find which provider a region code belongs to (region codes are unique across our catalog)."""
    for prov, reg, _meta in iter_regions():
        if reg == region:
            return prov
    return None
