"""Carbon readings (via the repository) + a workload CO2 ESTIMATE.

The estimate turns a workload into average watts (power model) -> kWh/month ->
multiply by grid intensity. Clearly an estimate, not a measurement.
"""
from __future__ import annotations

from ..models import CarbonReading, Workload, Provider
from ..data.repository import CarbonRepository
from ..data.static_data import power_model


async def carbon_now(repo: CarbonRepository, provider: Provider, region: str) -> CarbonReading:
    return await repo.carbon_now(provider, region)


def workload_kwh_per_month(workload: Workload) -> float:
    pm = power_model()
    watts = workload.vcpu * pm["watts_per_vcpu"] + workload.ram_gb * pm["watts_per_gb_ram"]
    watts *= pm["pue_default"]
    kwh = watts / 1000.0 * workload.hours_per_month
    return kwh


def estimate_kg_co2_per_month(workload: Workload, reading: CarbonReading) -> float:
    kwh = workload_kwh_per_month(workload)
    grams = kwh * reading.g_co2_per_kwh
    return round(grams / 1000.0, 2)


def watts_per_vcpu_at(provider: str, cpu_utilization: float) -> float:
    """Average watts per vCPU at a given CPU utilisation (0..1): idle minimum plus the load share of
    the gap to full load (Cloud Carbon Footprint method). Unknown providers use the AWS range."""
    pm = power_model()
    lo = pm["min_watts_per_vcpu"].get(provider, pm["min_watts_per_vcpu"]["aws"])
    hi = pm["max_watts_per_vcpu"].get(provider, pm["max_watts_per_vcpu"]["aws"])
    u = max(0.0, min(1.0, cpu_utilization))
    return lo + u * (hi - lo)


def workload_kwh_per_month_at(workload: Workload, provider: str, cpu_utilization: float) -> float:
    """Like workload_kwh_per_month, but CPU power follows utilisation instead of assuming full load.
    RAM power is unchanged (memory draws roughly the same whether busy or not)."""
    pm = power_model()
    watts = workload.vcpu * watts_per_vcpu_at(provider, cpu_utilization) + workload.ram_gb * pm["watts_per_gb_ram"]
    return watts * pm["pue_default"] / 1000.0 * workload.hours_per_month


def estimate_kg_co2_per_month_at(workload: Workload, reading: CarbonReading, cpu_utilization: float) -> float:
    kwh = workload_kwh_per_month_at(workload, reading.provider, cpu_utilization)
    return round(kwh * reading.g_co2_per_kwh / 1000.0, 2)
