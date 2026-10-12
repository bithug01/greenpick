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


class HourlyCarbon(BaseModel):
    """One hour's grid carbon intensity, for scheduling deferrable work."""
    period: str                       # the hour label from the source (e.g. "2026-10-12T03")
    g_co2_per_kwh: float


class CleanestWindow(BaseModel):
    """The lowest-average contiguous run of N hours — for timing a job of known duration."""
    window_hours: int
    start_period: str                 # the hour the window begins (start your job here)
    end_period: str                   # the last hour in the window
    avg_g_co2_per_kwh: float           # mean intensity across the window
    hours: list[HourlyCarbon] = []     # the per-hour breakdown of the chosen window


class HourOfDayStat(BaseModel):
    """Average carbon for a given hour-of-day across the days in the recent window."""
    hour_of_day: int                   # 0..23 (UTC, matching the source timestamps)
    avg_g_co2_per_kwh: float
    days_observed: int                 # how many days contributed to this average


class DailyPatternAdvice(BaseModel):
    """The recurring time-of-day pattern for a region, for timing a RECURRING job (e.g. nightly).

    This is a daily pattern over the N days we have, NOT a 7-day weekly pattern — the free data
    windows are only a few days, so we honestly report 'cleanest time of day', not 'day of week'."""
    region: str
    provider: Provider
    source: str
    quality: DataQuality
    days_analyzed: int
    hours_analyzed: int
    by_hour_of_day: list[HourOfDayStat] = []     # all 0..23 that had data, cleanest first
    cleanest_hour_of_day: Optional[int] = None
    dirtiest_hour_of_day: Optional[int] = None
    potential_reduction_pct: Optional[float] = None
    note: str = ""
    limitations: str = ""


class SchedulingAdvice(BaseModel):
    """Cleanest hours to run a deferrable job in a region, from recent history."""
    region: str
    provider: Provider
    source: str
    quality: DataQuality
    hours_analyzed: int
    cleanest: list[HourlyCarbon]      # lowest-carbon hours, cleanest first
    dirtiest_g_co2_per_kwh: Optional[float] = None
    cleanest_g_co2_per_kwh: Optional[float] = None
    potential_reduction_pct: Optional[float] = None   # cleanest vs dirtiest
    # Window mode (set when window_hours >= 2): the best contiguous run to start a job of that length.
    window: Optional[CleanestWindow] = None
    window_reduction_pct: Optional[float] = None       # best vs worst same-length window
    note: str = ""


class FamilyOption(BaseModel):
    """One instance family as a greener-compute candidate, same size & region."""
    family: str
    arch: str                                   # "x86" | "arm"
    cpu: str
    relative_energy: float                      # energy for the same work; lower = greener
    energy_saving_vs_current_pct: Optional[float] = None   # vs. the user's current family
    est_kg_co2_per_month: Optional[float] = None
    co2_saving_vs_current_pct: Optional[float] = None
    rating: Optional[str] = None                # "green" | "yellow" | "red", relative to the options
    note: str = ""


class GreenerComputeAdvice(BaseModel):
    """Greener same-size instance families in the same region, ranked by energy efficiency."""
    provider: Provider
    region: str
    current_family: Optional[str] = None
    grid_intensity_g_co2_per_kwh: Optional[float] = None
    carbon_source: Optional[str] = None
    carbon_quality: Optional[str] = None
    options: list[FamilyOption] = []            # greenest first
    recommended_family: Optional[str] = None
    rationale: str = ""
    limitations: str = ""


class TrainingRegionOption(BaseModel):
    """One region as a place to run a training job, with its carbon for this run."""
    provider: Provider
    region: str
    grid_intensity_g_co2_per_kwh: float
    carbon_source: str
    carbon_quality: str
    est_kg_co2: float                            # for the whole run, in this region
    vs_baseline_pct: Optional[float] = None      # negative = cleaner than baseline/current
    rating: Optional[str] = None                 # "green" | "yellow" | "red", relative


class TrainingCarbonAdvice(BaseModel):
    """Carbon of a GPU training run, with greener WHERE (region) and WHEN (hours) guidance."""
    gpu: str                                      # canonical GPU key
    gpu_name: str
    gpu_count: int
    gpu_hours: float                              # total accelerator-hours for the run
    utilization: float
    est_energy_kwh: float
    # Placement:
    region: Optional[str] = None                  # the resolved/queried region (if one was given)
    options: list[TrainingRegionOption] = []      # ranked greener-first (when ranking regions)
    recommended_region: Optional[str] = None
    # Timing (reuses cleanest-hours scheduling for the chosen/greenest region):
    cleanest_hours: list[HourlyCarbon] = []
    cleanest_window: Optional["CleanestWindow"] = None   # set when the run is >= 2h wall-clock
    timing_reduction_pct: Optional[float] = None
    timing_source: Optional[str] = None
    timing_quality: Optional[str] = None
    rationale: str = ""
    limitations: str = ""


class DataLocalityWarning(BaseModel):
    """Whether running compute away from where the data lives will cost you in egress.

    The core 'does the greener-region move backfire?' check. Primary signal is egress COST;
    transfer carbon is a secondary, deliberately-coarse figure."""
    compute_location: str                       # "provider/region"
    data_location: str                          # "provider/region"
    monthly_cross_boundary_gb: float
    locality: str                               # "same_region" | "cross_region_same_cloud" | "cross_cloud"
    severity: str                               # "none" | "low" | "medium" | "high"
    est_monthly_egress_usd: Optional[float] = None
    est_monthly_transfer_kg_co2: Optional[float] = None   # secondary, coarse
    carbon_saving_kg_co2_from_move: Optional[float] = None # echoed back if provided
    net_carbon_verdict: Optional[str] = None    # set only when a saving was supplied
    warning: str = ""
    recommendation: str = ""
    limitations: str = ""


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
    # Per-axis relative rating within the candidate set: "green" | "yellow" | "red".
    # Relative, not absolute — "best available among your options", shown next to the raw value.
    carbon_rating: Optional[str] = None
    latency_rating: Optional[str] = None
    cost_rating: Optional[str] = None
    tradeoff: Optional[str] = None                  # one-line plain-English summary


class Recommendation(BaseModel):
    """The full answer: ranked candidates + a pick + honest caveats."""
    candidates: list[RegionCandidate]
    recommended_region: Optional[str] = None
    rationale: str = ""
    limitations: str = ""
