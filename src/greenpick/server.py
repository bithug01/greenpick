"""MCP server: exposes GreenPick's 15 tools over FastMCP.

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
    training_service, forecast_service, serving_service, metric_scaffold_service,
    rightsizing_service, inference_service,
)
from .models import ServingHub
from .services.data_hint import with_hint
from .data.typical_repository import typical_context

# Sent to every MCP client at connect. Agents learn a server from its tool list, not its README, and
# the tool list starts with region-picking — so without this they lead with the rarest decision and
# skip the most valuable one. This names the strongest uses first and the reporting rules that matter.
INSTRUCTIONS = """\
GreenPick advises on cloud infrastructure decisions BEFORE you deploy, weighing carbon, cost and \
latency together. Strongest uses, in order:
1. Right-sizing (rightsizing_check): an over-provisioned instance cut to a standard, buyable size \
saves money and carbon in the same move. Lead with the monthly dollar saving.
2. Scheduling deferrable jobs: cleanest_hours_to_run (one-off), cleanest_time_of_day (recurring), \
carbon_forecast (EU day-ahead).
3. GPU training and LLM inference footprints: estimate_training_carbon (gpu_hours is the TOTAL across \
all GPUs; report wall_clock_hours as the run length), estimate_inference_carbon.
4. Efficiency and placement: greener_instance_family, compare_regions_tri_axis, greener_alternative_to, \
serving_pattern_advice; carbon_metric_scaffold for an app to track its own estimated carbon.
Before recommending a region move, run data_locality_egress_check: egress can erase the win. Mention \
any residency_note.
Every carbon figure carries source and quality fields. Report 'typical', 'mock', 'cached' or \
'historical' values as such, never as live readings — including figures derived from them, such as a kg CO2 saving. \
When a result includes live_data_hint, pass it on: it says why the data isn't live and how to turn \
live data on. If a call fails or output is missing, say so rather than describing \
what the tool would return. GreenPick estimates; it does not measure running systems or report model \
accuracy. Use explain_methodology_and_limits when asked how a number was produced.\
"""

mcp = FastMCP("greenpick", instructions=INSTRUCTIONS)
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
    return with_hint(rec.model_dump())


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
    return with_hint(rec.model_dump())


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
    return with_hint({
        "provider": provider,
        "region": region,
        "estimated_kg_co2_per_month": kg,
        "grid_intensity_g_co2_per_kwh": reading.g_co2_per_kwh,
        "carbon_source": reading.source,
        "carbon_quality": reading.quality,
        "note": "Estimate only: documented power model x grid intensity. Not a measurement.",
    })


@mcp.tool()
async def region_carbon_now(provider: str, region: str) -> dict:
    """Current grid carbon intensity for a region, with source, timestamp, and data freshness.
    When the reading is live, also says how it compares with what's typical for that hour this month
    (vs_typical: cleaner_than_usual / about_usual / dirtier_than_usual) — useful for "is now a good
    moment to run this?"."""
    reading = await carbon_service.carbon_now(_repo, provider, region)  # type: ignore[arg-type]
    out = reading.model_dump()
    if reading.quality in ("live", "live_estimated", "cached"):
        ctx = typical_context(provider, region, reading.g_co2_per_kwh, reading.timestamp)
        if ctx:
            out.update(ctx)
    return with_hint(out)


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
    return with_hint(advice.model_dump())


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
    return with_hint(advice.model_dump())


@mcp.tool()
async def estimate_inference_carbon(
    size_class: str,
    monthly_requests: float,
    avg_output_tokens: int = 300,
    region: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    """Energy + CO2 of running an LLM INFERENCE workload (serving queries) — the inference-side
    sibling of estimate_training_carbon. Give the model SIZE CLASS (small | mid | large |
    frontier_dense | moe, or a param alias like '8b' / '70b' / 'moe'), monthly request volume, and
    avg OUTPUT tokens per request (output drives inference energy). Pass `region` to add CO2 at live
    grid intensity. Returns a LOW-HIGH kWh/CO2 band (wide on purpose — serving choices move the same
    model many-fold). Directional, most trustworthy for self-hosted/open models; keyed on size class,
    NOT a named-model leaderboard. Smaller size class is the biggest lever."""
    advice = await inference_service.estimate_inference_carbon(
        _repo, size_class, monthly_requests, avg_output_tokens=avg_output_tokens,  # type: ignore[arg-type]
        region=region, provider=provider,  # type: ignore[arg-type]
    )
    return with_hint(advice.model_dump())


@mcp.tool()
async def rightsizing_check(
    provider: str,
    region: str,
    vcpu: float,
    ram_gb: float,
    cpu_utilization: float,
    ram_utilization: Optional[float] = None,
    hours_per_month: float = 730,
) -> dict:
    """Right-sizing (the #1 FinOps win) with a carbon twin: if you're over-provisioned, a smaller
    size cuts BOTH cost and carbon — same work, less waste, no tradeoff. Give the provisioned size
    (vcpu, ram_gb) and observed CPU utilisation (0..1, e.g. 0.2 for 20%); optionally RAM utilisation.
    Returns the right-sized target (keeps ~40% headroom) with the monthly $ AND kg CO2 saving. Lead
    with the cost number, carbon is the twin. Directional, design-time — uses the utilisation you
    report, not a reading of your fleet."""
    advice = await rightsizing_service.rightsizing_check(
        _repo, provider, region, vcpu, ram_gb, cpu_utilization,  # type: ignore[arg-type]
        ram_utilization=ram_utilization, hours_per_month=hours_per_month,
    )
    return with_hint(advice.model_dump())


@mcp.tool()
async def carbon_metric_scaffold(
    language: str = "python",
    region: Optional[str] = None,
    provider: Optional[str] = None,
    vcpu: float = 1,
    ram_gb: float = 2,
) -> dict:
    """Emit paste-in instrumentation so the user's OWN app can report an ESTIMATED carbon metric
    over time. Consider offering this when the user is building an app/service and wants ongoing
    visibility into its footprint. GreenPick returns a code snippet (Python in v1) + the power-model
    coefficients + a methodology note; the app measures observable proxies (CPU utilisation, vCPU/RAM,
    uptime) and multiplies by GreenPick's power model x the region's grid intensity. Pass `region`
    to bake in live grid intensity. The emitted number is a DIRECTIONAL estimate, self-labelled, NOT
    metered energy — and it's for SELF-tracking, not ranking against other apps. GreenPick does not
    run or measure anything itself."""
    scaffold = await metric_scaffold_service.carbon_metric_scaffold(
        _repo, language=language, region=region, provider=provider,  # type: ignore[arg-type]
        vcpu=vcpu, ram_gb=ram_gb,
    )
    return with_hint(scaffold.model_dump())


@mcp.tool()
async def serving_pattern_advice(
    hubs: list[dict],
    vcpu: float = 1,
    ram_gb: float = 2,
    providers: Optional[list[str]] = None,
) -> dict:
    """Design-time advice for a USER-FACING PLATFORM: should you serve users from ONE region or
    SEVERAL? Consider calling this when the user is building a web app / dashboard / API that serves
    end users. Give `hubs` as where your users are — a list like
    [{"name":"eu","share":0.4},{"name":"us","share":0.4},{"name":"apac","share":0.2}] (known names
    us/eu/uk/apac/au/india/japan/sa resolve automatically, or pass lat+lon). Rough shares are fine.
    Scores single-region-for-all vs one-region-per-hub on weighted latency + grid carbon, and flags
    the multi-region catches: cross-region data-sync egress and cross-jurisdiction residency. This is
    design-time guidance, NOT a runtime meter — it never measures your running app."""
    parsed = [
        ServingHub(
            name=str(h.get("name", f"hub{i}")),
            lat=float(h.get("lat", 0) or 0), lon=float(h.get("lon", 0) or 0),
            share=float(h.get("share", 1.0 / max(1, len(hubs)))),
        )
        for i, h in enumerate(hubs)
    ]
    advice = await serving_service.serving_pattern(
        _repo, parsed, Workload(vcpu=vcpu, ram_gb=ram_gb),
        providers=[p for p in (providers or [])] or None,  # type: ignore[list-item]
    )
    return with_hint(advice.model_dump())


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
    return with_hint(advice.model_dump())


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
    return with_hint(advice.model_dump())


@mcp.tool()
async def cleanest_time_of_day(provider: str, region: str) -> dict:
    """For a RECURRING job (e.g. a nightly batch you run every day), find the region's cleanest
    time of day — each hour-of-day averaged across the recent days of data. Returns the cleanest/
    dirtiest hour-of-day and the % gap. Honest scope: a DAILY pattern over the few days of free
    data, NOT a 7-day day-of-week pattern. Use `cleanest_hours_to_run` for a one-off job's timing."""
    advice = await scheduling_service.cleanest_time_of_day(_repo, provider, region)  # type: ignore[arg-type]
    return with_hint(advice.model_dump())


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
    Give the GPU (e.g. 'a100', 'h100', 'l4'), how many (gpu_count), and gpu_hours = TOTAL
    accelerator-hours across ALL GPUs — e.g. 8 GPUs running for 10 hours is gpu_hours=80, not 10.
    The output echoes wall_clock_hours (~gpu_hours / gpu_count) for reporting. Omit
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
    return with_hint(advice.model_dump())


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
        "inference": "LLM inference carbon is keyed on model SIZE CLASS (not a named product) with a wide LOW-HIGH band (quantisation/batching/serving move the same model many-fold); output tokens drive it. Directional, most trustworthy for self-hosted/open models; NOT a named-model leaderboard.",
        "forecast": "Day-ahead forecast is RELATIVE: upcoming hours ranked by forecast wind+solar output (ENTSO-E A69), not an absolute gCO2/kWh forecast. EU only; US/uncovered zones degrade to the recent historical pattern (labelled 'historical').",
        "data_residency": "GreenPick flags when a recommended move CROSSES a jurisdiction (esp. leaving the EEA) as a geographic heads-up only. It does NOT assess legal/GDPR compliance, does not encode adequacy decisions, and is not legal advice — confirm with your own data governance.",
        "ignored": "Embodied/hardware carbon and provider renewable-energy certificates.",
        "fallback_data": "Used when live data isn't available (no key, the source didn't respond, or GreenPick isn't set to live). 'typical' = this calendar month's average intensity and average hour-of-day profile (UTC) for the region, computed from 12 months of real hourly EIA-930 / ENTSO-E data with GreenPick's own emission factors (bundled typical.json, refreshed by scripts/refresh_typical.py) — a realistic norm, not a current reading. 'annual_average' = the country's yearly lifecycle grid intensity from Ember (via Our World in Data; bundled annual.json with source and year), for regions with no free hourly data (Singapore, Tokyo, Mumbai/Pune, Sydney — national figures, so Sydney's is a lower bound for its coal-heavier state) — sound for comparing regions, no timing signal (no hourly profile). 'mock' = a hand-set illustrative value with a synthetic hourly pattern, a last resort no catalog region relies on; timing advice on mock isn't meaningful. Both carry a live_data_hint saying why the result isn't live and how to turn live data on.",
        "data_sources": "GREENPICK_CARBON_SOURCE=auto routes US regions to EIA-930 and EU regions to ENTSO-E (both free, key needed), and Canadian regions to Hydro-Québec (Québec) and IESO (Ontario) open data (free, no key). All mixes are weighted with the same per-fuel factors. Without live data a region uses its clearly-labelled typical value (or mock where no free source exists). Electricity Maps is available when selected explicitly (GREENPICK_CARBON_SOURCE=electricitymaps).",
    }
