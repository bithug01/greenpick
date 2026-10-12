"""Ballpark monthly cost (compute + egress) from the dated static pricing table.

Deterministic. Returns None if the provider isn't in the table rather than guessing.
NOT a quote — see data/pricing.json caveats.
"""
from __future__ import annotations

from ..models import Workload, Provider
from ..data.static_data import pricing


def estimate_monthly_cost_usd(provider: Provider, workload: Workload) -> float | None:
    table = pricing().get(provider)
    if not table:
        return None
    compute = (
        workload.vcpu * table["compute_usd_per_vcpu_hour"]
        + workload.ram_gb * table["compute_usd_per_gb_ram_hour"]
    ) * workload.hours_per_month
    egress = workload.est_monthly_egress_gb * table["egress_usd_per_gb"]
    return round(compute + egress, 2)
