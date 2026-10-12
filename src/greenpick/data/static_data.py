"""Loaders for the bundled static JSON (regions, pricing, power model).

Cached at import; these change rarely and are versioned in-repo.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def regions() -> dict:
    return json.loads((_DATA_DIR / "regions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def pricing() -> dict:
    return json.loads((_DATA_DIR / "pricing.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def power_model() -> dict:
    return json.loads((_DATA_DIR / "power.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def emission_factors() -> dict:
    """Per-fuel gCO2/kWh factors (keyed by EIA fueltype code)."""
    return json.loads((_DATA_DIR / "emission_factors.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def instance_families() -> dict:
    """Directional perf-per-watt multipliers for general-purpose instance families."""
    return json.loads((_DATA_DIR / "instance_families.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def network_model() -> dict:
    """Directional data-transfer energy intensity (kWh/GB) for the egress carbon signal."""
    return json.loads((_DATA_DIR / "network.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def gpu_power() -> dict:
    """Directional GPU/accelerator power model (TDP + utilization + host overhead) for training."""
    return json.loads((_DATA_DIR / "gpu_power.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _gpu_index() -> dict:
    """Lowercased lookup from GPU key OR alias -> (canonical_key, spec dict)."""
    idx: dict[str, tuple[str, dict]] = {}
    for key, spec in gpu_power().get("gpus", {}).items():
        idx[key.lower()] = (key, spec)
        for alias in spec.get("aliases", []):
            idx[alias.lower()] = (key, spec)
    return idx


def resolve_gpu(name: str) -> tuple[str, dict] | None:
    """Resolve a user-supplied GPU name (case-insensitive, alias-aware) -> (canonical_key, spec),
    or None if unknown. e.g. 'A100', 'a100-sxm', 'tesla-t4' all resolve."""
    if not name:
        return None
    return _gpu_index().get(name.strip().lower())


def iter_regions():
    """Yield (provider, region_code, meta) for every known region."""
    data = regions()
    for provider, regs in data.items():
        if provider.startswith("_"):
            continue
        for code, meta in regs.items():
            yield provider, code, meta


def region_meta(provider: str, region: str) -> dict | None:
    return regions().get(provider, {}).get(region)
