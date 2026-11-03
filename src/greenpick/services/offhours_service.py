"""Off-hours scheduling: "this doesn't need to run 24/7."

Dev, test, staging, demo and batch environments are often left running all night and all weekend.
Switching them off when nobody uses them is the other FinOps basic next to right-sizing, and it has
the same dual benefit: cost and carbon both scale with running hours, so every hour you don't run
saves both, with no tradeoff in the hours you do.

Design-time and directional. It reuses GreenPick's cost table and power model unchanged: the only
new input is how many hours a week the environment actually needs to be on.
"""
from __future__ import annotations

from ..data.repository import CarbonRepository
from ..models import OffHoursAdvice, Provider, Workload
from . import carbon_service, cost_service

HOURS_PER_WEEK_ALWAYS_ON = 168
HOURS_PER_MONTH_ALWAYS_ON = 730                         # GreenPick's always-on baseline
WEEKS_PER_MONTH = HOURS_PER_MONTH_ALWAYS_ON / HOURS_PER_WEEK_ALWAYS_ON   # ~4.345
_MIN_SAVING_PCT = 10.0                                  # below this, not worth the machinery


async def offhours_check(
    repo: CarbonRepository,
    provider: Provider,
    region: str,
    vcpu: float,
    ram_gb: float,
    hours_per_week_on: float,
) -> OffHoursAdvice:
    scheduled_hours = round(min(HOURS_PER_MONTH_ALWAYS_ON, hours_per_week_on * WEEKS_PER_MONTH), 1)
    now_wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=HOURS_PER_MONTH_ALWAYS_ON)
    sched_wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=scheduled_hours)

    reading = await carbon_service.carbon_now(repo, provider, region)
    cost_now = cost_service.estimate_monthly_cost_usd(provider, now_wl)
    cost_s = cost_service.estimate_monthly_cost_usd(provider, sched_wl)
    carbon_now = carbon_service.estimate_kg_co2_per_month(now_wl, reading)
    carbon_s = carbon_service.estimate_kg_co2_per_month(sched_wl, reading)

    usd_saving = round(cost_now - cost_s, 2) if cost_now is not None and cost_s is not None else None
    cost_pct = round((cost_now - cost_s) / cost_now * 100, 1) if cost_now and cost_s is not None else None
    kg_saving = round(carbon_now - carbon_s, 2)
    carbon_pct = round((carbon_now - carbon_s) / carbon_now * 100, 1) if carbon_now > 0 else None
    on_share = round(scheduled_hours / HOURS_PER_MONTH_ALWAYS_ON * 100, 1)
    worthwhile = bool(carbon_pct is not None and carbon_pct >= _MIN_SAVING_PCT)

    if worthwhile:
        usd_txt = f"~${usd_saving:,.0f}/mo" if usd_saving is not None else "a lower bill"
        rationale = (
            f"Running ~{hours_per_week_on:g} h a week instead of around the clock (168 h) means it is on "
            f"{on_share:.0f}% of the time: ~{cost_pct:.0f}% cheaper ({usd_txt} saved) AND "
            f"~{carbon_pct:.0f}% less carbon (~{kg_saving:.1f} kg CO2/mo, {reading.quality} grid data). "
            f"Same hours of use, nothing running when nobody is there. Only worth it for an "
            f"environment that can be off, and you need something to stop and start it on schedule.")
    else:
        rationale = (
            f"At ~{hours_per_week_on:g} h a week it is already on {on_share:.0f}% of the time, so "
            f"switching it off outside those hours would save under {_MIN_SAVING_PCT:.0f}% — not worth "
            f"building a scheduler for. Look to right-sizing or region choice instead.")

    return OffHoursAdvice(
        provider=provider, region=region, vcpu=vcpu, ram_gb=ram_gb,
        hours_per_week_on=hours_per_week_on,
        hours_per_month_now=HOURS_PER_MONTH_ALWAYS_ON, hours_per_month_scheduled=scheduled_hours,
        on_share_pct=on_share,
        cost_now_usd_per_month=cost_now, cost_scheduled_usd_per_month=cost_s,
        monthly_usd_saving=usd_saving, cost_saving_pct=cost_pct,
        carbon_now_kg_per_month=carbon_now, carbon_scheduled_kg_per_month=carbon_s,
        monthly_kg_co2_saving=kg_saving, carbon_saving_pct=carbon_pct,
        is_worthwhile=worthwhile,
        carbon_source=reading.source, carbon_quality=reading.quality,
        rationale=rationale,
        limitations=(
            "Directional, compute only. A stopped instance still costs for its attached disks, IP "
            "addresses and snapshots, so the real bill falls a little less than shown. Reserved "
            "instances and savings plans are paid for whether the instance runs or not, so they cancel "
            "the saving: this applies to on-demand capacity. Assumes the instance works as hard when it "
            "is on, and that start-up time and data warm-up are acceptable. Carbon uses today's grid "
            "intensity; the hours you actually run may be cleaner or dirtier (see cleanest_time_of_day). "
            "Hours per week: weekdays 9-17 is 40, weekdays 7-19 is 60, around the clock is 168."),
    )
