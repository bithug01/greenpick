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
