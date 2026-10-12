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
from . import carbon_service

LIMITATIONS = (
    "Egress cost is DIRECTIONAL: a flat per-GB rate from a dated table — it ignores free tiers, "
    "tiered/inter-region pricing, and same-AZ exemptions, so treat it as a floor-ish ballpark, not "
    "a quote. Transfer carbon uses a single kWh/GB coefficient whose published estimates vary by "
    "orders of magnitude; it's order-of-magnitude only. You supply where data lives and how much "
    "crosses — GreenPick can't infer your architecture."
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
            est_monthly_egress_usd=0.0, est_monthly_transfer_kg_co2=0.0,
            warning="Compute and data are co-located — no cross-boundary egress for this flow.",
            recommendation="No locality penalty. Choose the region on carbon/latency/cost as usual.",
            limitations=LIMITATIONS,
        )

    severity = _bump_severity_for_volume(severity, monthly_cross_boundary_gb)

    # Egress is billed on the SOURCE of the outbound bytes. For a compute<->data flow the
    # dominant charge is data LEAVING the data's region (reads) and/or compute's region (writes);
    # we use the data region's egress rate as the representative directional figure.
    data_table = pricing().get(data_provider) or {}
    egress_rate = data_table.get("egress_usd_per_gb")
    est_cost = (round(monthly_cross_boundary_gb * egress_rate, 2)
                if egress_rate is not None else None)

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
    cost_txt = f"~${est_cost:,.0f}/mo in egress" if est_cost is not None else "egress cost (rate unknown)"
    warning = (f"Compute and data are separated {sep}: ~{monthly_cross_boundary_gb:,.0f} GB/mo would "
               f"cross the boundary, costing {cost_txt} plus ~{transfer_kg:.1f} kg CO2/mo of extra "
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

    return DataLocalityWarning(
        compute_location=compute_loc, data_location=data_loc,
        monthly_cross_boundary_gb=monthly_cross_boundary_gb,
        locality=locality, severity=severity,
        est_monthly_egress_usd=est_cost, est_monthly_transfer_kg_co2=transfer_kg,
        carbon_saving_kg_co2_from_move=carbon_saving_kg_co2_from_move,
        net_carbon_verdict=verdict,
        warning=warning, recommendation=rec, limitations=LIMITATIONS,
    )
