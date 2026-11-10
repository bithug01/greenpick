"""Would serverless change the math? An always-on server vs. paying only for the time code runs.

A mostly idle service on an always-on server pays (and draws power) around the clock, even when it is
doing nothing. A request-driven serverless platform (AWS Lambda, Google Cloud Run) charges, and keeps
hardware busy, only while requests run. Which is cheaper depends on how much traffic there is: low or
spiky traffic favours serverless, steady high traffic favours a server. This compares the two on cost
and on estimated carbon, and gives the monthly request count where they break even on cost.

Directional on both axes. The server side uses the utilisation-aware power model (Cloud Carbon
Footprint min/max watts per vCPU). The serverless side counts only the compute time requests run, at
the CCF Lambda assumptions (1,792 MB of memory = 1 vCPU, 50% average utilisation), so it is a LOWER
BOUND: platform overhead such as warm instances and control planes is not published and is not
included. Prices are dated on-demand list prices, before free tiers and discounts.
"""
from __future__ import annotations

from typing import Optional

from ..data.repository import CarbonRepository
from ..data.static_data import power_model, pricing
from ..models import Workload
from . import carbon_service, cost_service

HOURS_PER_MONTH = 730


def _serverless_cost(provider: str, requests: float, active_seconds: float, memory_gb: float,
                     vcpu_equiv: float) -> tuple[Optional[float], Optional[float]]:
    """(cost, cost per million requests) for a month, before free tiers; (None, None) if unpriced."""
    p = (pricing().get("_serverless_usd") or {}).get(provider)
    if not p:
        return None, None
    if provider == "aws":
        per_req_compute = (active_seconds / requests if requests else 0) * memory_gb * p["usd_per_gb_second"]
    else:   # gcp, Cloud Run request-based: vCPU-seconds + GiB-seconds while requests run
        per_req_compute = ((active_seconds / requests if requests else 0)
                           * (vcpu_equiv * p["usd_per_vcpu_second"] + memory_gb * p["usd_per_gib_second"]))
    per_req = per_req_compute + p["usd_per_million_requests"] / 1e6
    return round(per_req * requests, 2), per_req * 1e6


async def serverless_check(
    repo: CarbonRepository,
    provider: str,
    region: str,
    vcpu: float,
    ram_gb: float,
    avg_cpu_utilization: float,
    monthly_requests: float,
    avg_duration_ms: float,
    function_memory_gb: float = 1.0,
) -> dict:
    pm = power_model()
    reading = await carbon_service.carbon_now(repo, provider, region)   # type: ignore[arg-type]

    # Always-on server: the bill for every hour, and power that follows its real utilisation.
    vm = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=HOURS_PER_MONTH)
    vm_cost = cost_service.estimate_monthly_cost_usd(provider, vm)      # type: ignore[arg-type]
    vm_kg = carbon_service.estimate_kg_co2_per_month_at(vm, reading, avg_cpu_utilization)
    vm_kg_full = carbon_service.estimate_kg_co2_per_month(vm, reading)

    # Serverless: only the time requests run, with CPU allocated in proportion to memory.
    active_seconds = monthly_requests * avg_duration_ms / 1000.0
    active_hours = active_seconds / 3600.0
    vcpu_equiv = min(6.0, function_memory_gb * 1024 / pm["serverless_mb_per_vcpu"])
    sl = Workload(vcpu=max(vcpu_equiv, 1e-6), ram_gb=function_memory_gb, hours_per_month=max(active_hours, 1e-9))
    sl_kg = (carbon_service.estimate_kg_co2_per_month_at(sl, reading, pm["serverless_assumed_utilization"])
             if active_hours > 0 else 0.0)
    sl_cost, per_million = _serverless_cost(provider, monthly_requests, active_seconds, function_memory_gb, vcpu_equiv)

    breakeven = None
    if vm_cost is not None and per_million:
        breakeven = round(vm_cost / per_million * 1e6)
    cost_saving = round(vm_cost - sl_cost, 2) if vm_cost is not None and sl_cost is not None else None
    cost_pct = round(cost_saving / vm_cost * 100, 1) if cost_saving is not None and vm_cost else None
    kg_saving = round(vm_kg - sl_kg, 2)
    carbon_pct = round(kg_saving / vm_kg * 100, 1) if vm_kg > 0 else None

    # Does this traffic fit inside the provider's monthly free tier? Then the real bill could be $0.
    free = (pricing().get("_serverless_usd") or {}).get(provider) or {}
    in_free_tier = None
    if free:
        req_ok = monthly_requests <= free.get("free_requests", 0)
        if provider == "aws":
            use_ok = active_seconds * function_memory_gb <= free.get("free_gb_seconds", 0)
        else:
            use_ok = (active_seconds * vcpu_equiv <= free.get("free_vcpu_seconds", 0)
                      and active_seconds * function_memory_gb <= free.get("free_gib_seconds", 0))
        in_free_tier = bool(req_ok and use_ok)

    if cost_saving is None:
        cost_txt = ("Serverless cost isn't priced for this provider in GreenPick (check the provider's pricing "
                    "page); the comparison below is carbon only.")
        verdict = "carbon_only"
    elif cost_saving > 0:
        cost_txt = (f"Serverless would cost about ${sl_cost:,.2f} a month against ${vm_cost:,.2f} for the always-on "
                    f"server: about ${cost_saving:,.0f} a month less ({cost_pct:.0f}%).")
        verdict = "serverless_cheaper"
    else:
        cost_txt = (f"Serverless would cost about ${sl_cost:,.2f} a month against ${vm_cost:,.2f} for the always-on "
                    f"server: about ${-cost_saving:,.0f} a month MORE. At this traffic a server is the cheaper choice.")
        verdict = "server_cheaper"
    free_txt = (" This traffic fits within the provider's monthly free tier, so the actual serverless bill "
                "could be $0." if in_free_tier else "")
    be_txt = (f" They break even at about {breakeven:,} requests a month at this duration and memory; above that, "
              "the server wins on cost." if breakeven else "")
    summary = (f"{cost_txt}{free_txt}{be_txt} Estimated carbon: about {sl_kg:.2f} kg CO2 a month serverless (a lower bound) "
               f"against {vm_kg:.2f} kg for the server at {avg_cpu_utilization * 100:.0f}% CPU use "
               f"({reading.quality} grid data).")

    return {
        "summary": summary,
        "verdict": verdict,
        "provider": provider,
        "region": region,
        "server": {"vcpu": vcpu, "ram_gb": ram_gb, "avg_cpu_utilization": avg_cpu_utilization,
                   "hours_per_month": HOURS_PER_MONTH},
        "serverless": {"monthly_requests": monthly_requests, "avg_duration_ms": avg_duration_ms,
                       "function_memory_gb": function_memory_gb, "vcpu_equivalent": round(vcpu_equiv, 2),
                       "billed_hours_per_month": round(active_hours, 1)},
        "server_cost_usd_per_month": vm_cost,
        "serverless_cost_usd_per_month": sl_cost,
        "monthly_usd_saving": cost_saving,
        "cost_saving_pct": cost_pct,
        "breakeven_monthly_requests": breakeven,
        "within_free_tier": in_free_tier,
        "server_kg_co2_per_month": vm_kg,
        "server_kg_co2_per_month_at_full_load": vm_kg_full,
        "serverless_kg_co2_per_month_lower_bound": sl_kg,
        "monthly_kg_co2_saving": kg_saving,
        "carbon_saving_pct": carbon_pct,
        "carbon_source": reading.source,
        "carbon_quality": reading.quality,
        "limitations": (
            "Directional. Serverless bills each request's full duration, including time spent waiting on a "
            "database or another service, while a server handles many requests at once, so I/O-heavy services "
            "favour a server more than these figures suggest. Serverless cost is on-demand list price before free tiers (AWS gives 1M requests and "
            "400,000 GB-seconds a month free; Cloud Run 2M requests and some vCPU/GiB-seconds), and excludes "
            "API gateway, data transfer and provisioned-concurrency charges. Serverless carbon counts only the "
            "time requests run and leaves out platform overhead such as warm instances, so it is a lower bound. "
            "The server side assumes on-demand pricing; reserved capacity and savings plans change the cost. "
            "Cold starts, request time limits and concurrency limits can rule serverless out regardless of price. "
            "Power follows Cloud Carbon Footprint's min/max watts per vCPU."),
    }
