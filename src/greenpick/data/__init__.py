"""Data layer: swappable carbon sources behind one repository interface.

`get_repository()` is the single place that reads config and picks a source, so the rest
of the app never hard-codes a provider.
"""
from __future__ import annotations

from ..config import SETTINGS
from .repository import CarbonRepository
from .mock_repository import MockCarbonRepository


def get_repository() -> CarbonRepository:
    source = SETTINGS.carbon_source
    if source == "electricitymaps":
        from .electricitymaps_repository import ElectricityMapsRepository
        return ElectricityMapsRepository(SETTINGS.electricitymaps_token, SETTINGS.cache_ttl_seconds)
    if source == "eia":
        from .eia_repository import EIARepository
        return EIARepository(SETTINGS.eia_api_key, SETTINGS.cache_ttl_seconds)
    if source == "entsoe":
        from .entsoe_repository import ENTSOERepository
        return ENTSOERepository(SETTINGS.entsoe_token, SETTINGS.cache_ttl_seconds)
    if source == "auto":
        # Route per region: EIA for US (eia_ba), ENTSO-E for EU (entsoe_eic), else mock.
        from .auto_repository import AutoRepository
        return AutoRepository(SETTINGS.eia_api_key, SETTINGS.entsoe_token, SETTINGS.cache_ttl_seconds)
    return MockCarbonRepository()
