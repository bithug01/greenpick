"""Data-locality / egress warning.

The trap this guards against: you move COMPUTE to a greener (often farther) region, but your
DATA stays put — a database, object store, or another service. Every byte crossing that
boundary is billed as egress and burns extra network energy. A naive "greener region" pick can
be eaten alive by egress cost, and sometimes by the transfer carbon too.

This tool is explicit by design: the caller tells us where compute runs, where the data lives,
and how much crosses per month. We classify the separation, give a DIRECTIONAL egress-cost
ballpark (the decision-relevant number), a deliberately-coarse transfer-carbon figure, and — if
the caller supplies the carbon saving the move buys — a net verdict on whether the move still
pays off.

Honesty posture: egress COST leads (it's concrete, if approximate). Transfer CARBON is secondary
and loudly flagged as order-of-magnitude, because the science on kWh/GB is unsettled.
"""
from __future__ import annotations

from typing import Optional

from ..models import DataLocalityWarning, Provider, CarbonReading
from ..data.repository import CarbonRepository
from ..data.static_data import pricing, network_model
from . import carbon_service, residency_service

LIMITATIONS = (
    "Egress cost is DIRECTIONAL: a LOW-HIGH range for the locality tier (same-region / cross-region / "
    "cross-cloud) from dated list prices — it ignores free-tier allowances, committed-use/negotiated "
    "discounts, exact region-pair rates, and NAT/load-balancer fees, so treat it as a ballpark, not a "
    "quote. Transfer carbon uses a single kWh/GB coefficient whose published estimates vary by orders "
    "of magnitude; it's order-of-magnitude only. You supply where data lives and how much crosses — "
    "GreenPick can't infer your architecture."
)


def _classify(compute_provider: str, compute_region: str,
              data_provider: str, data_region: str) -> tuple[str, str]:
    """Return (locality, severity). Severity is the structural separation, before volume."""
    if compute_provider == data_provider and compute_region == data_region:
        return "same_region", "none"
    if compute_provider == data_provider:
        return "cross_region_same_cloud", "medium"
    return "cross_cloud", "high"


def _bump_severity_for_volume(severity: str, gb: float) -> str:
    """A tiny cross-boundary trickle barely matters; a firehose matters a lot. Nudge severity
    by monthly volume so the warning tracks real exposure, not just topology."""
    if severity == "none":
        return "none"
    order = ["low", "medium", "high"]
    base = {"low": 0, "medium": 1, "high": 2}[severity]
    if gb >= 1000:
        base = min(2, base + 1)
    elif gb < 50:
        base = max(0, base - 1)
    return order[base]


async def data_locality_check(
    repo: CarbonRepository,
    compute_provider: Provider,
    compute_region: str,
    data_provider: Provider,
    data_region: str,
    monthly_cross_boundary_gb: float,
    carbon_saving_kg_co2_from_move: Optional[float] = None,
) -> DataLocalityWarning:
    compute_loc = f"{compute_provider}/{compute_region}"
    data_loc = f"{data_provider}/{data_region}"
    locality, severity = _classify(compute_provider, compute_region, data_provider, data_region)

    if locality == "same_region":
        return DataLocalityWarning(
            compute_location=compute_loc, data_location=data_loc,
            monthly_cross_boundary_gb=monthly_cross_boundary_gb,
            locality=locality, severity="none",
            egress_rate_usd_per_gb_low=0.0, egress_rate_usd_per_gb_high=0.0,
            est_monthly_egress_usd_low=0.0, est_monthly_egress_usd_high=0.0,
            est_monthly_transfer_kg_co2=0.0,
            warning="Compute and data are co-located — no cross-boundary egress for this flow.",
            recommendation="No locality penalty. Choose the region on carbon/latency/cost as usual.",
            limitations=LIMITATIONS,
        )

    severity = _bump_severity_for_volume(severity, monthly_cross_boundary_gb)

    # Egress is a TIER LADDER by where the bytes cross — not one flat rate. Price the tier we just
    # classified, as a LOW-HIGH range (region-pair rates vary). For cross-cloud/internet the rate
    # is provider-specific, so anchor the high end to the data provider's own internet rate.
    tiers = pricing().get("_egress_tiers_usd_per_gb", {})
    tier = tiers.get(locality, {})
    rate_low = tier.get("low")
    rate_high = tier.get("high")
    if locality == "cross_cloud":
        prov_internet = (pricing().get(data_provider) or {}).get("egress_usd_per_gb")
        if prov_internet is not None and rate_high is not None:
            rate_high = max(rate_high, prov_internet)   # don't under-quote this provider's internet rate
    cost_low = round(monthly_cross_boundary_gb * rate_low, 2) if rate_low is not None else None
    cost_high = round(monthly_cross_boundary_gb * rate_high, 2) if rate_high is not None else None

    # Transfer carbon: energy to move the bytes x the grid intensity where that energy is drawn.
    # Use the data region's grid as the representative intensity (coarse — energy is spread along
    # the path, but this keeps it tied to a real, live number).
    kwh_per_gb = network_model()["kwh_per_gb_transfer"]
    reading: CarbonReading = await carbon_service.carbon_now(repo, data_provider, data_region)
    transfer_kwh = monthly_cross_boundary_gb * kwh_per_gb
    transfer_kg = round(transfer_kwh * reading.g_co2_per_kwh / 1000.0, 2)

    # Net verdict only if the caller told us what the move saves.
    verdict = None
    if carbon_saving_kg_co2_from_move is not None:
        net = carbon_saving_kg_co2_from_move - transfer_kg
        if net > 0:
            verdict = (f"Still a net win: the move saves ~{carbon_saving_kg_co2_from_move:.1f} kg "
                       f"CO2/mo, the extra transfer costs ~{transfer_kg:.1f} kg, net "
                       f"~{net:.1f} kg saved. (Egress COST may still argue against it.)")
        else:
            verdict = (f"Backfires on carbon: the move saves ~{carbon_saving_kg_co2_from_move:.1f} kg "
                       f"CO2/mo but the extra transfer adds ~{transfer_kg:.1f} kg - net "
                       f"~{abs(net):.1f} kg WORSE. Keep compute near the data, or move the data too.")

    sep = ("across clouds" if locality == "cross_cloud" else "across regions in the same cloud")
    if cost_low is not None and cost_high is not None:
        cost_txt = (f"roughly ${cost_low:,.0f}-${cost_high:,.0f}/mo in egress "
                    f"(~${rate_low:.2f}-${rate_high:.2f}/GB for this tier)")
    else:
        cost_txt = "an egress cost (rate unknown for this tier)"
    warning = (f"Compute and data are separated {sep}: ~{monthly_cross_boundary_gb:,.0f} GB/mo would "
               f"cross the boundary, costing {cost_txt}, plus ~{transfer_kg:.1f} kg CO2/mo of extra "
               f"transfer. A greener-region move can be undone by this.")

    if severity == "high":
        rec = ("High exposure. Co-locate compute with the data, or move the data to the greener "
               "region too. If you can't, confirm the carbon/cost saving beats this egress penalty "
               "before moving compute alone.")
    elif severity == "medium":
        rec = ("Moderate exposure. Weigh the egress cost against the region's carbon/cost saving; "
               "co-locating is usually cleaner and cheaper.")
    else:
        rec = ("Low exposure at this volume. The locality penalty is small — the region's "
               "carbon/latency/cost tradeoff probably dominates.")

    # Residency heads-up: compute processing data that lives in another jurisdiction is exactly the
    # residency-sensitive case. Flag the data-region -> compute-region crossing (neutral, not legal).
    residency_note = residency_service.residency_flag(
        data_provider, data_region, compute_provider, compute_region,
    )

    return DataLocalityWarning(
        compute_location=compute_loc, data_location=data_loc,
        monthly_cross_boundary_gb=monthly_cross_boundary_gb,
        locality=locality, severity=severity,
        egress_rate_usd_per_gb_low=rate_low, egress_rate_usd_per_gb_high=rate_high,
        est_monthly_egress_usd_low=cost_low, est_monthly_egress_usd_high=cost_high,
        est_monthly_transfer_kg_co2=transfer_kg,
        carbon_saving_kg_co2_from_move=carbon_saving_kg_co2_from_move,
        net_carbon_verdict=verdict, residency_note=residency_note,
        warning=warning, recommendation=rec, limitations=LIMITATIONS,
    )
