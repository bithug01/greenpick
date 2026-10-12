"""Domain models shared across data sources, services, and tools.

Pydantic for validation at the MCP boundary (inputs arrive as loosely-typed JSON).
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


Provider = Literal["aws", "gcp", "azure"]
DataQuality = Literal["live", "live_estimated", "cached", "annual_average", "mock"]


class Workload(BaseModel):
    """A long-running web/API service — the only workload shape in v1."""
    vcpu: float = Field(gt=0, description="vCPUs provisioned")
    ram_gb: float = Field(gt=0, description="RAM in GB")
    est_monthly_egress_gb: float = Field(ge=0, default=0, description="Outbound GB/month")
    hours_per_month: float = Field(gt=0, default=730, description="Running hours/month (730 = always-on)")


class GeoPoint(BaseModel):
    lat: float
    lon: float


class CarbonReading(BaseModel):
    """Grid carbon intensity for a region at a point in time."""
    region: str
    provider: Provider
    g_co2_per_kwh: float = Field(ge=0)
    source: str                      # e.g. "electricitymaps", "eia", "mock"
    timestamp: str                   # ISO 8601
    quality: DataQuality             # how trustworthy / fresh this reading is


class RegionCandidate(BaseModel):
    """One region scored on all three axes — the tri-axis payload."""
    region: str
    provider: Provider
    carbon: CarbonReading
    carbon_rank: Optional[int] = None            # 1 = cleanest among candidates
    carbon_vs_baseline_pct: Optional[float] = None  # negative = cleaner than the baseline region
    est_monthly_cost_usd: Optional[float] = None    # compute + egress ballpark
    latency_ms_estimate: Optional[float] = None     # to the user's location
    added_latency_ms: Optional[float] = None        # vs. the baseline region
    tradeoff: Optional[str] = None                  # one-line plain-English summary


class Recommendation(BaseModel):
    """The full answer: ranked candidates + a pick + honest caveats."""
    candidates: list[RegionCandidate]
    recommended_region: Optional[str] = None
    rationale: str = ""
    limitations: str = ""
