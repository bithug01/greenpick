"""Does moving the DATA too pay off, or should it stay put?

The follow-on to data_locality_egress_check. Say you move compute to a greener region but the data
stays behind. Every month, some GB cross between them and cost egress plus a little transfer carbon.
You can instead migrate the data once, which costs egress once, and then that traffic stops crossing.
This works out when the one-off cost is paid back by the monthly cost you stop paying.

The maths is deliberately simple. The one-off move and the monthly flow cross the same boundary, so
they use the same $/GB rate and the same kWh/GB coefficient. That makes payback in months equal to
GB to migrate divided by GB a month that would stop crossing, for money and for carbon alike. The
dollar and kg figures are shown on top so the size of the numbers is visible.

It only weighs egress. Storage price differences, request charges, downtime, double-running during the
migration and the effort of doing it are NOT included.
"""
from __future__ import annotations

from typing import Optional

from ..data.repository import CarbonRepository
from ..data.static_data import network_model
from . import carbon_service, locality_service, residency_service


def _usd(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


async def migration_payoff(
    repo: CarbonRepository,
    data_provider: str, data_region: str,
    compute_provider: str, compute_region: str,
    data_gb_to_migrate: float,
    monthly_cross_boundary_gb: float,
    horizon_months: float = 12,
) -> dict:
    locality, _sev = locality_service._classify(
        compute_provider, compute_region, data_provider, data_region)
    where = f"{data_provider}/{data_region} to {compute_provider}/{compute_region}"
    if locality == "same_region":
        return {
            "summary": "Nothing to migrate: the data is already in the compute region.",
            "data_location": f"{data_provider}/{data_region}",
            "compute_location": f"{compute_provider}/{compute_region}",
            "verdict": "already_co_located",
        }

    low, high = locality_service.egress_rate_range(locality, data_provider)
    reading = await carbon_service.carbon_now(repo, data_provider, data_region)   # type: ignore[arg-type]
    kwh_per_gb = network_model()["kwh_per_gb_transfer"]
    kg_per_gb = kwh_per_gb * reading.g_co2_per_kwh / 1000.0

    one_off_kg = round(data_gb_to_migrate * kg_per_gb, 2)
    monthly_kg = round(monthly_cross_boundary_gb * kg_per_gb, 2)
    one_off_usd = (round(data_gb_to_migrate * low, 2), round(data_gb_to_migrate * high, 2)) \
        if low is not None and high is not None else (None, None)
    monthly_usd = (round(monthly_cross_boundary_gb * low, 2), round(monthly_cross_boundary_gb * high, 2)) \
        if low is not None and high is not None else (None, None)

    payback_months: Optional[float] = None
    if monthly_cross_boundary_gb > 0:
        payback_months = round(data_gb_to_migrate / monthly_cross_boundary_gb, 1)

    net_usd = None
    net_kg = None
    if payback_months is not None:
        net_kg = round(horizon_months * monthly_kg - one_off_kg, 2)
        if one_off_usd[0] is not None:
            # worst case: pay the high rate to move and avoid only the low rate; best case: the reverse
            net_usd = (round(horizon_months * monthly_usd[0] - one_off_usd[1], 2),
                       round(horizon_months * monthly_usd[1] - one_off_usd[0], 2))

    residency = residency_service.residency_flag(
        data_provider, data_region, compute_provider, compute_region)

    straddle = (net_usd is not None and net_usd[0] < 0 < net_usd[1])
    egress_only = " Egress only: this does not judge whether the compute should be in that region."
    if monthly_cross_boundary_gb <= 0:
        verdict = "no_ongoing_traffic"
        summary = (f"Moving the data buys no egress saving: no GB a month cross between "
                   f"{where}, so the one-off migration (~{data_gb_to_migrate:,.0f} GB) has nothing to pay "
                   "it back. Only move it for other reasons.")
    elif payback_months <= horizon_months:
        verdict = "pays_back"
        summary = (f"Moving the data too pays back in about {payback_months:g} months "
                   f"(~{data_gb_to_migrate:,.0f} GB once vs ~{monthly_cross_boundary_gb:,.0f} GB a month "
                   f"no longer crossing), within your {horizon_months:g}-month horizon.")
        if straddle:
            summary += (f" In dollars it could land either side of zero over the horizon "
                        f"(net {_usd(net_usd[0])} to {_usd(net_usd[1])}); the carbon saving is "
                        f"{'positive' if net_kg and net_kg > 0 else 'not positive'} (~{net_kg:,.1f} kg).")
        summary += egress_only
    else:
        verdict = "does_not_pay_back"
        summary = (f"Moving the data too does NOT pay back within {horizon_months:g} months: it takes "
                   f"about {payback_months:g} months (~{data_gb_to_migrate:,.0f} GB once vs "
                   f"~{monthly_cross_boundary_gb:,.0f} GB a month no longer crossing). Leave the data "
                   "where it is, or re-check the volumes.") + egress_only

    return {
        "summary": summary,
        "verdict": verdict,
        "data_location": f"{data_provider}/{data_region}",
        "compute_location": f"{compute_provider}/{compute_region}",
        "locality": locality,
        "data_gb_to_migrate": data_gb_to_migrate,
        "monthly_cross_boundary_gb": monthly_cross_boundary_gb,
        "horizon_months": horizon_months,
        "payback_months": payback_months,
        "egress_rate_usd_per_gb_low": low, "egress_rate_usd_per_gb_high": high,
        "one_off_migration_egress_usd_low": one_off_usd[0],
        "one_off_migration_egress_usd_high": one_off_usd[1],
        "monthly_egress_avoided_usd_low": monthly_usd[0],
        "monthly_egress_avoided_usd_high": monthly_usd[1],
        "one_off_transfer_kg_co2": one_off_kg,
        "monthly_transfer_kg_co2_avoided": monthly_kg,
        "net_over_horizon_usd_low": net_usd[0] if net_usd else None,
        "net_over_horizon_usd_high": net_usd[1] if net_usd else None,
        "net_over_horizon_kg_co2": net_kg,
        "transfer_carbon_source": reading.source,
        "transfer_carbon_quality": reading.quality,
        "residency_note": residency,
        "limitations": (
            "Egress only. The cost is a dated list-price ballpark (a low-high range, no free tiers or "
            "negotiated discounts) and the transfer carbon uses one kWh/GB coefficient that is "
            "order-of-magnitude. Storage price differences, API/request charges, downtime, running both "
            "copies during the migration and the work of migrating are NOT included. It assumes moving "
            "the data stops the monthly traffic entirely. Payback is GB to migrate divided by GB a month "
            "that stops crossing, because both use the same rate."),
    }
