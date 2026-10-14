"""carbon_metric_scaffold: emit paste-in instrumentation so an app measures its OWN estimated carbon.

GreenPick does not run or measure anything here. Software can't read its own wattage, so the app
measures the cheap proxies it CAN observe (CPU utilisation, provisioned vCPU/RAM, uptime) and
applies GreenPick's power model x the region's grid intensity to emit an ESTIMATED gCO2 metric.
GreenPick's job is to supply (a) the code and (b) the coefficients that make the number meaningful.

Hard guardrails baked into the output:
- The metric is self-labelled `estimated_gco2*` with a comment stating it's directional, model-based,
  NOT metered energy — because it will live in production dashboards and get quoted.
- v1 is SELF-tracking (watch your own app over time/version/region/load), NOT cross-app ranking,
  which would need a shared spec to be anything but noise.
- Deliverable is a snippet + coefficients + methodology note, NOT a framework/SDK.
"""
from __future__ import annotations

from typing import Optional

from ..models import CarbonMetricScaffold, Provider
from ..data.repository import CarbonRepository
from ..data.static_data import power_model
from . import carbon_service

SUPPORTED_LANGUAGES = ("python",)

METHODOLOGY = (
    "estimated_gco2_per_hour = ((vcpu * watts_per_vcpu * cpu_utilisation) + (ram_gb * watts_per_gb_ram)) "
    "* pue / 1000 * grid_g_co2_per_kwh. Proxies (CPU util, vCPU, RAM, uptime) are what an app can "
    "actually observe; the watts/PUE come from GreenPick's documented power model; grid intensity from "
    "the region. It is an ESTIMATE, not a measurement of real energy drawn."
)

LIMITATIONS = (
    "DIRECTIONAL estimate, not metered energy — software cannot read its true wattage, so this models "
    "it from CPU utilisation and a published power model. Ignores GPU/accelerator, disk/network, "
    "embodied carbon, and real hardware variance. If you hardcode a grid intensity it goes stale — "
    "refresh it (or call region_carbon_now) periodically. Use for SELF-tracking over time, NOT to rank "
    "against other apps (different boundaries/coefficients make that meaningless)."
)


def _python_snippet(vcpu_default: float, ram_default: float, pm: dict,
                     grid: Optional[float], region: Optional[str]) -> str:
    watts_vcpu = pm["watts_per_vcpu"]
    watts_ram = pm["watts_per_gb_ram"]
    pue = pm["pue_default"]
    grid_literal = repr(grid) if grid is not None else "None"
    region_comment = f"  # region: {region}" if region else ""
    return f'''# --- GreenPick carbon metric (PASTE INTO YOUR APP) ---------------------------------
# estimated_gco2 is a DIRECTIONAL ESTIMATE from CPU utilisation x a documented power model
# x grid carbon intensity. It is NOT a measurement of real energy drawn. Use it to watch THIS
# app's footprint over time/versions/regions - not to compare against other apps.
# Model + coefficients: GreenPick (power.json). Methodology in the accompanying note.
import time

# --- Coefficients from GreenPick's power model (safe to keep; refresh grid intensity periodically)
_WATTS_PER_VCPU = {watts_vcpu}
_WATTS_PER_GB_RAM = {watts_ram}
_PUE = {pue}
_GRID_G_CO2_PER_KWH = {grid_literal}{region_comment}   # set/refresh for YOUR region; see region_carbon_now


class CarbonEstimator:
    """Estimates this process's grid carbon from observable proxies. Directional, not metered."""

    def __init__(self, vcpu: float = {vcpu_default}, ram_gb: float = {ram_default},
                 grid_g_co2_per_kwh: float | None = _GRID_G_CO2_PER_KWH):
        self.vcpu = vcpu
        self.ram_gb = ram_gb
        self.grid = grid_g_co2_per_kwh
        self._start = time.time()

    def estimated_watts(self, cpu_utilisation: float) -> float:
        """cpu_utilisation in 0..1 (e.g. psutil.cpu_percent()/100)."""
        u = max(0.0, min(1.0, cpu_utilisation))
        return (self.vcpu * _WATTS_PER_VCPU * u + self.ram_gb * _WATTS_PER_GB_RAM) * _PUE

    def estimated_gco2_per_hour(self, cpu_utilisation: float) -> float | None:
        if self.grid is None:
            return None   # no grid intensity set -> can't estimate carbon honestly
        return self.estimated_watts(cpu_utilisation) / 1000.0 * self.grid

    def estimated_gco2_since_start(self, avg_cpu_utilisation: float) -> float | None:
        rate = self.estimated_gco2_per_hour(avg_cpu_utilisation)
        if rate is None:
            return None
        hours = (time.time() - self._start) / 3600.0
        return rate * hours


# Example: expose as a metric (Prometheus-style gauge, a log line, or a /metrics field).
#   import psutil
#   est = CarbonEstimator(vcpu=2, ram_gb=4)
#   gco2_per_hour = est.estimated_gco2_per_hour(psutil.cpu_percent() / 100.0)
#   # -> publish `estimated_gco2_per_hour` to your dashboard
# ---------------------------------------------------------------------------------'''


async def carbon_metric_scaffold(
    repo: CarbonRepository,
    language: str = "python",
    region: Optional[str] = None,
    provider: Optional[Provider] = None,
    vcpu: float = 1,
    ram_gb: float = 2,
) -> CarbonMetricScaffold:
    lang = language.strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        return CarbonMetricScaffold(
            language=language,
            how_to_use=f"Language '{language}' not supported yet. v1 emits Python; "
                       f"the math (see methodology) ports easily to any language.",
            methodology=METHODOLOGY, limitations=LIMITATIONS,
        )

    pm = power_model()
    grid = None
    source = quality = None
    if region is not None:
        prov = provider or _guess_provider(region)
        if prov is not None:
            reading = await carbon_service.carbon_now(repo, prov, region)  # type: ignore[arg-type]
            grid = reading.g_co2_per_kwh
            source, quality = reading.source, reading.quality

    code = _python_snippet(vcpu, ram_gb, pm, grid, region)
    how = ("Paste the snippet into your app. Instantiate CarbonEstimator with your instance's vcpu/"
           "ram_gb, feed it CPU utilisation (e.g. psutil.cpu_percent()/100), and publish "
           "estimated_gco2_per_hour to your dashboard/metrics. Set the grid intensity for your "
           "region — if you gave GreenPick a region it's baked in; otherwise call region_carbon_now "
           "and refresh it periodically so it doesn't go stale.")
    return CarbonMetricScaffold(
        language="python", region=region,
        grid_intensity_g_co2_per_kwh=grid, carbon_source=source, carbon_quality=quality,
        coefficients={
            "watts_per_vcpu": pm["watts_per_vcpu"],
            "watts_per_gb_ram": pm["watts_per_gb_ram"],
            "pue_default": pm["pue_default"],
        },
        code=code, how_to_use=how, methodology=METHODOLOGY, limitations=LIMITATIONS,
    )


def _guess_provider(region: str) -> Optional[str]:
    from ..data.static_data import iter_regions
    for prov, reg, _meta in iter_regions():
        if reg == region:
            return prov
    return None
