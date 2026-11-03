"""A paste-ready justification for a region choice, for a pull request or decision record.

GreenPick already computes the carbon, cost, latency and egress numbers behind a region move. What a
team needs next is a short paragraph they can put in the PR. This turns the numbers into that
paragraph. It adds no new data or maths, and it keeps the honesty labels attached: each carbon figure
says what kind of reading it is (live, typical, yearly average), and the text says these are design-time
estimates, not measurements or a quote.

If the move is NOT an improvement, the text says so plainly instead of dressing it up.
"""
from __future__ import annotations

from typing import Optional

from ..data.repository import CarbonRepository
from ..data.static_data import network_model, region_meta
from ..models import GeoPoint, Workload
from . import carbon_service, cost_service, latency_service, locality_service, residency_service

_QUALITY_PHRASE = {
    "live": "live grid reading",
    "cached": "recent cached grid reading",
    "typical": "typical average for this time of year",
    "annual_average": "yearly national average",
    "historical": "recent historical average",
    "forecast": "forecast",
    "mock": "illustrative placeholder value",
}


def _phrase(quality: str) -> str:
    return _QUALITY_PHRASE.get(quality, quality)


def _signed_pct(new: float, old: float) -> Optional[float]:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


async def region_move_justification(
    repo: CarbonRepository,
    from_provider: str, from_region: str,
    to_provider: str, to_region: str,
    vcpu: float, ram_gb: float,
    hours_per_month: float = 730,
    user_lat: Optional[float] = None, user_lon: Optional[float] = None,
    monthly_cross_boundary_gb: float = 0,
) -> dict:
    wl = Workload(vcpu=vcpu, ram_gb=ram_gb, hours_per_month=hours_per_month)
    a = await carbon_service.carbon_now(repo, from_provider, from_region)    # type: ignore[arg-type]
    b = await carbon_service.carbon_now(repo, to_provider, to_region)        # type: ignore[arg-type]
    kg_a = carbon_service.estimate_kg_co2_per_month(wl, a)
    kg_b = carbon_service.estimate_kg_co2_per_month(wl, b)
    kg_saving = round(kg_a - kg_b, 2)
    carbon_pct = _signed_pct(kg_b, kg_a)
    intensity_pct = _signed_pct(b.g_co2_per_kwh, a.g_co2_per_kwh)

    cost_a = cost_service.estimate_monthly_cost_usd(from_provider, wl)       # type: ignore[arg-type]
    cost_b = cost_service.estimate_monthly_cost_usd(to_provider, wl)         # type: ignore[arg-type]
    cost_delta = round(cost_b - cost_a, 2) if cost_a is not None and cost_b is not None else None

    added_latency = None
    if user_lat is not None and user_lon is not None:
        user = GeoPoint(lat=user_lat, lon=user_lon)
        la = latency_service.estimate_latency_ms(from_provider, from_region, user)   # type: ignore[arg-type]
        lb = latency_service.estimate_latency_ms(to_provider, to_region, user)       # type: ignore[arg-type]
        if la is not None and lb is not None:
            added_latency = round(lb - la)

    # Egress: the data is assumed to STAY in the region you are moving away from.
    egress_low = egress_high = transfer_kg = net_kg = None
    locality = "same_region"
    if monthly_cross_boundary_gb > 0:
        locality, _sev = locality_service._classify(from_provider, from_region, to_provider, to_region)
        if locality != "same_region":
            low, high = locality_service.egress_rate_range(locality, from_provider)
            if low is not None and high is not None:
                egress_low = round(monthly_cross_boundary_gb * low, 2)
                egress_high = round(monthly_cross_boundary_gb * high, 2)
            transfer_kg = round(monthly_cross_boundary_gb * network_model()["kwh_per_gb_transfer"]
                                * a.g_co2_per_kwh / 1000.0, 2)
            net_kg = round(kg_saving - transfer_kg, 2)

    residency = residency_service.residency_flag(from_provider, from_region, to_provider, to_region)
    size = f"{vcpu:g} vCPU / {ram_gb:g} GB"
    move = f"{from_provider}/{from_region} to {to_provider}/{to_region}"

    # ---- the paragraph ----
    parts: list[str] = []
    if kg_saving > 0:
        parts.append(
            f"Moving this {size} service from {from_provider}/{from_region} to "
            f"{to_provider}/{to_region} cuts its estimated grid carbon from {kg_a:.1f} to {kg_b:.1f} kg "
            f"CO2 a month ({carbon_pct:+.0f}%), because the grid is cleaner there "
            f"({a.g_co2_per_kwh:.0f} to {b.g_co2_per_kwh:.0f} gCO2/kWh).")
    elif kg_saving < 0:
        parts.append(
            f"Moving this {size} service from {from_provider}/{from_region} to "
            f"{to_provider}/{to_region} would RAISE its estimated grid carbon from {kg_a:.1f} to "
            f"{kg_b:.1f} kg CO2 a month ({carbon_pct:+.0f}%) ({a.g_co2_per_kwh:.0f} to "
            f"{b.g_co2_per_kwh:.0f} gCO2/kWh), so this move is not justified on carbon.")
    else:
        parts.append(
            f"Moving this {size} service from {from_provider}/{from_region} to "
            f"{to_provider}/{to_region} makes no estimated difference to grid carbon.")
    if cost_delta is None:
        pass
    elif cost_delta == 0:
        parts.append("The compute list-price estimate is unchanged.")
    elif cost_delta < 0:
        parts.append(f"The compute list-price estimate falls by about ${abs(cost_delta):,.0f} a month.")
    else:
        parts.append(f"The compute list-price estimate rises by about ${cost_delta:,.0f} a month.")
    if added_latency is not None:
        if added_latency > 0:
            parts.append(f"Estimated latency for the stated users rises by about {added_latency} ms.")
        elif added_latency < 0:
            parts.append(f"Estimated latency for the stated users falls by about {abs(added_latency)} ms.")
        else:
            parts.append("Estimated latency for the stated users is about the same.")
    if net_kg is not None:
        cost_part = (f" and about ${egress_low:,.0f}-${egress_high:,.0f} a month in egress"
                     if egress_low is not None else "")
        if net_kg > 0:
            parts.append(
                f"The data stays in {from_provider}/{from_region} (~{monthly_cross_boundary_gb:,.0f} GB a "
                f"month crossing), which adds about {transfer_kg:.1f} kg CO2{cost_part}, "
                f"leaving a net saving of about {net_kg:.1f} kg CO2 a month.")
        else:
            parts.append(
                f"But the data stays in {from_provider}/{from_region} (~{monthly_cross_boundary_gb:,.0f} GB "
                f"a month crossing), which adds about {transfer_kg:.1f} kg CO2{cost_part}: the move "
                f"backfires on carbon by about {abs(net_kg):.1f} kg a month unless the data moves too.")
    elif (from_provider, from_region) != (to_provider, to_region):
        parts.append("Data transfer between the regions was not assessed (no cross-region GB a month "
                     "was given), so the net effect of keeping data behind is not included.")
    if residency:
        parts.append("Data residency: the move crosses jurisdictions, so confirm it against your "
                     "data-governance requirements.")
    parts.append(
        f"Carbon is a {_phrase(a.quality)} for {from_region} and a {_phrase(b.quality)} for {to_region}. "
        "These are design-time estimates from GreenPick, not measurements or a price quote.")
    pr_text = " ".join(parts)

    if kg_saving > 0:
        summary = (f"{move}: about {kg_saving:.1f} kg CO2 a month less"
                   + (f" ({net_kg:.1f} kg after data transfer)" if net_kg is not None else "")
                   + (f", {added_latency:+d} ms latency" if added_latency is not None else "") + ".")
    else:
        summary = f"{move}: not an improvement on carbon ({kg_saving:+.1f} kg CO2 a month)."

    return {
        "summary": summary,
        "pr_text": pr_text,
        "facts": {
            "from": f"{from_provider}/{from_region}", "to": f"{to_provider}/{to_region}",
            "workload": size, "hours_per_month": hours_per_month,
            "from_g_co2_per_kwh": a.g_co2_per_kwh, "to_g_co2_per_kwh": b.g_co2_per_kwh,
            "grid_intensity_change_pct": intensity_pct,
            "from_kg_co2_per_month": kg_a, "to_kg_co2_per_month": kg_b,
            "monthly_kg_co2_saving": kg_saving, "carbon_change_pct": carbon_pct,
            "from_carbon_quality": a.quality, "to_carbon_quality": b.quality,
            "from_carbon_source": a.source, "to_carbon_source": b.source,
            "compute_cost_change_usd_per_month": cost_delta,
            "added_latency_ms": added_latency,
            "locality": locality,
            "monthly_cross_boundary_gb": monthly_cross_boundary_gb,
            "est_monthly_egress_usd_low": egress_low, "est_monthly_egress_usd_high": egress_high,
            "est_monthly_transfer_kg_co2": transfer_kg,
            "net_monthly_kg_co2_saving_after_transfer": net_kg,
            "residency_note": residency,
        },
        "limitations": (
            "Formats numbers GreenPick already computes; it checks nothing new. Carbon is a grid-intensity "
            "estimate (see each quality label), cost is a list-price ballpark that does not vary by region "
            "within one provider, latency is a geographic estimate, and the egress figure is directional. "
            "The text assumes the data stays in the region you are moving away from. Review the wording "
            "before you paste it."),
    }
