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
