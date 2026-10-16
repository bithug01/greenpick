"""LLM inference carbon — the inference-side sibling of estimate_training_carbon.

Most of an LLM's lifetime carbon is INFERENCE (serving queries), not training. A developer building
on an LLM makes a carbon choice constantly and invisibly: which model (size), how many requests, how
many output tokens, where it runs. This estimates the energy + CO2 of that serving workload.

Honest scoping (per the data spike):
- Keyed on model SIZE CLASS, not named commercial products (vendors don't disclose serving hardware).
- OUTPUT tokens drive the estimate (generation dominates inference energy).
- Reported as a LOW-HIGH band, because quantisation/batching/serving move the same model many-fold.
- Carbon = energy x the region's live grid intensity (reuses the carbon repository), when a region
  is given. Directional; most trustworthy for self-hosted/open models.
"""
from __future__ import annotations

from typing import Optional

from ..models import Provider, InferenceCarbonAdvice
from ..data.repository import CarbonRepository
from ..data.static_data import inference_energy, resolve_size_class
from . import carbon_service

LIMITATIONS = (
    "DIRECTIONAL estimate, not a measurement. Keyed on model SIZE CLASS (not a named product — "
    "vendors don't publish serving hardware/batching). The LOW-HIGH band is wide on purpose: "
    "quantisation, batching, and request shaping move the same model's energy many-fold. Output "
    "tokens drive it; input tokens are ignored. MoE models use the 'moe' class (they run near their "
    "ACTIVE param count, not total). Most trustworthy for self-hosted/open models; a hosted API's "
    "real figure depends on the provider's undisclosed setup. Not for ranking named commercial models."
)


async def estimate_inference_carbon(
    repo: CarbonRepository,
    size_class: str,
    monthly_requests: float,
    avg_output_tokens: int = 300,
    region: Optional[str] = None,
    provider: Optional[Provider] = None,
) -> InferenceCarbonAdvice:
    resolved = resolve_size_class(size_class)
    if resolved is None:
        classes = ", ".join(inference_energy().get("size_classes", {}).keys())
        return InferenceCarbonAdvice(
            size_class=size_class, size_class_label=size_class,
            monthly_requests=monthly_requests, avg_output_tokens=avg_output_tokens,
            monthly_output_tokens=0, wh_per_1k_output_low=0, wh_per_1k_output_high=0,
            monthly_kwh_low=0, monthly_kwh_high=0,
            rationale=(f"Unknown size class '{size_class}'. Use one of: {classes} "
                       f"(or a param-count alias like 8b / 70b / moe)."),
            limitations=LIMITATIONS,
        )

    cls_key, spec = resolved
    lo = spec["wh_per_1k_output_tokens_low"]
    hi = spec["wh_per_1k_output_tokens_high"]

    monthly_output_tokens = monthly_requests * avg_output_tokens
    # Wh = (Wh per 1k output tokens) x (output tokens / 1000); kWh = Wh / 1000.
    kwh_low = round(lo * monthly_output_tokens / 1000.0 / 1000.0, 3)
    kwh_high = round(hi * monthly_output_tokens / 1000.0 / 1000.0, 3)

    advice = InferenceCarbonAdvice(
        size_class=cls_key, size_class_label=spec["label"],
        monthly_requests=monthly_requests, avg_output_tokens=avg_output_tokens,
        monthly_output_tokens=monthly_output_tokens,
        wh_per_1k_output_low=lo, wh_per_1k_output_high=hi,
        monthly_kwh_low=kwh_low, monthly_kwh_high=kwh_high,
        limitations=LIMITATIONS,
    )

    carbon_txt = ""
    if region is not None:
        prov = provider or _guess_provider(region)
        if prov is not None:
            reading = await carbon_service.carbon_now(repo, prov, region)  # type: ignore[arg-type]
            g = reading.g_co2_per_kwh
            advice.region = region
            advice.grid_intensity_g_co2_per_kwh = g
            advice.carbon_source = reading.source
            advice.carbon_quality = reading.quality
            advice.monthly_kg_co2_low = round(kwh_low * g / 1000.0, 2)
            advice.monthly_kg_co2_high = round(kwh_high * g / 1000.0, 2)
            carbon_txt = (f" In {prov}/{region} ({g:.0f} gCO2/kWh, {reading.source}) that's "
                          f"~{advice.monthly_kg_co2_low:.1f}-{advice.monthly_kg_co2_high:.1f} kg CO2/mo.")

    advice.rationale = (
        f"{spec['label']}: ~{monthly_requests:,.0f} requests/mo x ~{avg_output_tokens} output tokens "
        f"= ~{monthly_output_tokens/1e6:.1f}M output tokens -> ~{kwh_low:,.1f}-{kwh_high:,.1f} kWh/mo "
        f"(band reflects serving choices: quantisation/batching/shaping).{carbon_txt} A smaller size "
        f"class is the biggest lever - energy scales steeply with model size.")
    return advice


def _guess_provider(region: str) -> Optional[str]:
    from ..data.static_data import iter_regions
    for prov, reg, _meta in iter_regions():
        if reg == region:
            return prov
    return None
