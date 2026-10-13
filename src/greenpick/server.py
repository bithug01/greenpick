"""MCP server: exposes GreenPick's 11 tools over FastMCP.

Thin layer — parse/validate inputs, call services, return JSON-friendly dicts. All math
lives in services/; this file only wires tools to them.
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .models import Workload, GeoPoint, Provider
from .data import get_repository
from .services import (
    carbon_service, recommender, scheduling_service, instance_service, locality_service,
    training_service, forecast_service,
)

mcp = FastMCP("greenpick")
_repo = get_repository()


@mcp.tool()
async def compare_regions_tri_axis(
    user_lat: float,
    user_lon: float,
    vcpu: float,
    ram_gb: float,
    est_monthly_egress_gb: float = 0,
    providers: Optional[list[str]] = None,
    optimize_for: str = "carbon",
    max_added_latency_ms: Optional[float] = None,
    baseline_region: Optional[str] = None,
    regions: Optional[list[str]] = None,
) -> dict:
    """Rank candidate cloud regions by carbon, with cost + latency tradeoffs, and recommend one.
    Give the user's location (lat/lon) and the service shape (vcpu, ram_gb, egress). Pass `regions`
    (e.g. ["us-east-1","us-west-2","eu-west-1"]) to rank ONLY those you'd actually consider,
    instead of the whole catalog — your baseline is always kept in the comparison. If the pick is
    in a different region from where your data lives, run data_locality_egress_check before moving:
    cross-region/cross-cloud egress can erase the carbon/cost win."""
    rec = await recommender.compare_regions(
        _repo,
        providers=[p for p in (providers or [])] or None,  # type: ignore[list-item]
        user_location=GeoPoint(lat=user_lat, lon=user_lon),
        workload=Workload(vcpu=vcpu, ram_gb=ram_gb, est_monthly_egress_gb=est_monthly_egress_gb),
        optimize_for=optimize_for,
        max_added_latency_ms=max_added_latency_ms,
        baseline_region=baseline_region,
        regions=[r for r in (regions or [])] or None,
    )
    return rec.model_dump()


@mcp.tool()
async def greener_alternative_to(
    current_region: str,
    user_lat: float,
    user_lon: float,
    vcpu: float,
    ram_gb: float,
    est_monthly_egress_gb: float = 0,
    max_added_latency_ms: float = 100,
    providers: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
) -> dict:
    """You picked `current_region` — find the greenest region within +max_added_latency_ms,
    with the carbon/cost/latency delta vs. your current choice. The core 'nudge' tool. Pass
    `regions` to limit the search to options you'd actually move to; your current region is
    always included. Before accepting a move, run data_locality_egress_check if your data stays in
    the current region — the egress to feed compute from afar can outweigh the greener-region win."""
    rec = await recommender.compare_regions(
        _repo,
        providers=[p for p in (providers or [])] or None,  # type: ignore[list-item]
        user_location=GeoPoint(lat=user_lat, lon=user_lon),
        workload=Workload(vcpu=vcpu, ram_gb=ram_gb, est_monthly_egress_gb=est_monthly_egress_gb),
        optimize_for="carbon",
        max_added_latency_ms=max_added_latency_ms,
        baseline_region=current_region,
        regions=[r for r in (regions or [])] or None,
    )
    return rec.model_dump()


@mcp.tool()
async def estimate_workload_carbon(
    provider: str,
    region: str,
    vcpu: float,
    ram_gb: float,
    hours_per_month: float = 730,
) -> dict:
    """Rough kgCO2/month for a workload running in a region. An ESTIMATE (documented power
    model x grid intensity), not a measurement."""
    reading = await carbon_service.carbon_now(_repo, provider, region)  # type: ignore[arg-type]
    wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=hours_per_month)
    kg = carbon_service.estimate_kg_co2_per_month(wl, reading)
    return {
        "provider": provider,
        "region": region,
        "estimated_kg_co2_per_month": kg,
        "grid_intensity_g_co2_per_kwh": reading.g_co2_per_kwh,
        "carbon_source": reading.source,
        "carbon_quality": reading.quality,
        "note": "Estimate only: documented power model x grid intensity. Not a measurement.",
    }


@mcp.tool()
async def region_carbon_now(provider: str, region: str) -> dict:
    """Current grid carbon intensity for a region, with source, timestamp, and data freshness."""
    reading = await carbon_service.carbon_now(_repo, provider, region)  # type: ignore[arg-type]
    return reading.model_dump()


@mcp.tool()
async def cleanest_hours_to_run(
    provider: str, region: str, top_n: int = 3, window_hours: Optional[int] = None,
) -> dict:
    """Carbon-aware scheduling: given a region, report its cleanest recent hours so you can
    time a DEFERRABLE job (nightly ETL, batch, backups, training) when the grid is greenest.
    Returns the lowest-carbon hours + the % reduction vs. the dirtiest hour. Pass `window_hours`
    (e.g. 6) for a job of known duration — it finds the cleanest CONTIGUOUS run of that many hours
    to start at, since you can't split one job across scattered non-adjacent hours. Directional."""
    advice = await scheduling_service.cleanest_hours(
        _repo, provider, region, top_n, window_hours=window_hours,  # type: ignore[arg-type]
    )
    return advice.model_dump()


@mcp.tool()
async def greener_instance_family(
    provider: str,
    region: str,
    vcpu: float,
    ram_gb: float,
    current_family: Optional[str] = None,
    hours_per_month: float = 730,
) -> dict:
    """Suggest a greener SAME-SIZE instance family in the SAME region. The mechanism is
    performance-per-watt: a newer-generation or ARM (Graviton-class) family does the same
    work on less energy -> less CO2 at the region's grid intensity. Give your current family
    (e.g. 'm5', 'n2', 'Dv5') for a savings delta. Directional, not a measurement."""
    if not instance_service.is_supported_provider(provider):
        return {
            "provider": provider,
            "region": region,
            "error": f"Unsupported provider '{provider}'.",
            "supported_providers": list(instance_service.SUPPORTED_PROVIDERS),
            "options": [],
        }
    advice = await instance_service.greener_instance_family(
        _repo, provider, region, vcpu, ram_gb,  # type: ignore[arg-type]
        current_family=current_family, hours_per_month=hours_per_month,
    )
    return advice.model_dump()


@mcp.tool()
async def data_locality_egress_check(
    compute_provider: str,
    compute_region: str,
    data_provider: str,
    data_region: str,
    monthly_cross_boundary_gb: float,
    carbon_saving_kg_co2_from_move: Optional[float] = None,
) -> dict:
    """Will running compute away from where your DATA lives backfire via egress? Give where
    compute runs, where the data lives (provider+region), and monthly GB crossing between them.
    Returns a directional egress-COST ballpark, a coarse transfer-carbon figure, and — if you
    pass the carbon saving the greener-region move buys — whether it's still a net win. Use this
    before accepting a greener-region suggestion when your data stays put."""
    advice = await locality_service.data_locality_check(
        _repo, compute_provider, compute_region, data_provider, data_region,  # type: ignore[arg-type]
        monthly_cross_boundary_gb=monthly_cross_boundary_gb,
        carbon_saving_kg_co2_from_move=carbon_saving_kg_co2_from_move,
    )
    return advice.model_dump()


@mcp.tool()
async def carbon_forecast(
    provider: str, region: str, hours_ahead: int = 24, top_n: int = 5,
) -> dict:
    """Forward-looking scheduling: which UPCOMING hours will be cleanest? Uses the EU day-ahead
    wind+solar forecast (ENTSO-E) to rank the greenest hours over the next `hours_ahead`. This is
    a RELATIVE ranking (more forecast renewables = cleaner), not an absolute gCO2/kWh forecast.
    EU regions get a true forecast; US/uncovered regions degrade to the recent historical pattern
    (labelled 'historical'). Use this to PLAN a deferrable job, vs cleanest_hours_to_run (reactive)."""
    advice = await forecast_service.carbon_forecast(
        _repo, provider, region, hours_ahead=hours_ahead, top_n=top_n,  # type: ignore[arg-type]
    )
    return advice.model_dump()


@mcp.tool()
async def cleanest_time_of_day(provider: str, region: str) -> dict:
    """For a RECURRING job (e.g. a nightly batch you run every day), find the region's cleanest
    time of day — each hour-of-day averaged across the recent days of data. Returns the cleanest/
    dirtiest hour-of-day and the % gap. Honest scope: a DAILY pattern over the few days of free
    data, NOT a 7-day day-of-week pattern. Use `cleanest_hours_to_run` for a one-off job's timing."""
    advice = await scheduling_service.cleanest_time_of_day(_repo, provider, region)  # type: ignore[arg-type]
    return advice.model_dump()


@mcp.tool()
async def estimate_training_carbon(
    gpu: str,
    gpu_count: int,
    gpu_hours: float,
    region: Optional[str] = None,
    provider: Optional[str] = None,
    utilization: Optional[float] = None,
    top_n_regions: int = 5,
) -> dict:
    """Carbon of a GPU training run, with greener WHERE (region) and WHEN (hours) guidance.
    Give the GPU (e.g. 'a100', 'h100', 'l4'), how many, and total GPU-hours for the run. Omit
    `region` to rank regions greenest-first; pass one to score just that region. Training is both
    portable and deferrable, so this combines region choice with cleanest-hours timing. Directional
    (TDP-based energy); GPU availability per region is NOT checked - verify your card is offered there.
    Training data is often large: if your dataset lives in another region, run data_locality_egress_check
    before shipping the job to the greenest region - the data egress can outweigh the carbon saving."""
    advice = await training_service.estimate_training_carbon(
        _repo, gpu, gpu_count, gpu_hours,  # type: ignore[arg-type]
        region=region, provider=provider, utilization=utilization,  # type: ignore[arg-type]
        top_n_regions=top_n_regions,
    )
    return advice.model_dump()


@mcp.tool()
def explain_methodology_and_limits() -> dict:
    """GreenPick's assumptions and what it explicitly does NOT claim. Read this before trusting a number."""
    return {
        "what_it_is": "Directional, design-time guidance for choosing a greener cloud region.",
        "what_it_is_not": "Audited carbon accounting, ESG/Scope-2 reporting, or a real-time scheduler.",
        "carbon": "Grid carbon intensity by region, point-in-time. Not flow-traced consumption accounting.",
        "cost": "Ballpark from a dated static table (compute + egress). Not a quote.",
        "latency": "Great-circle geographic estimate, not a measured ping.",
        "carbon_estimate": "Workload CO2 = documented power model (vCPU/RAM -> watts) x PUE x grid intensity.",
        "instance_family": "Greener-family suggestion uses DIRECTIONAL perf-per-watt multipliers by generation/arch (ARM/Graviton-class = biggest win), not a benchmark of your workload.",
        "data_locality": "Egress check leads with a DIRECTIONAL cost ballpark (flat per-GB, ignores free tiers/tiered pricing); transfer carbon uses a single kWh/GB coefficient whose published estimates span orders of magnitude — order-of-magnitude only.",
        "training": "Training carbon uses published GPU TDP (peak, not your run's measured draw) x a utilization assumption + host overhead x PUE, then x the region's grid intensity. GPU availability per region is NOT checked. Ignores spot/on-demand, checkpointing, multi-node networking.",
        "forecast": "Day-ahead forecast is RELATIVE: upcoming hours ranked by forecast wind+solar output (ENTSO-E A69), not an absolute gCO2/kWh forecast. EU only; US/uncovered zones degrade to the recent historical pattern (labelled 'historical').",
        "ignored": "Embodied/hardware carbon and provider renewable-energy certificates.",
        "data_sources": "Electricity Maps free tier (primary); ENTSO-E / EIA / NESO fallbacks; annual averages offline.",
    }
