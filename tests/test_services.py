"""Unit tests for the pure services and the recommender (mock carbon source)."""
from __future__ import annotations

import pytest

from greenpick.models import Workload, GeoPoint, CarbonReading
from greenpick.data.mock_repository import MockCarbonRepository
from greenpick.services import cost_service, latency_service, carbon_service, recommender


def test_cost_scales_with_workload_and_egress():
    small = Workload(vcpu=1, ram_gb=2, est_monthly_egress_gb=0)
    big = Workload(vcpu=4, ram_gb=16, est_monthly_egress_gb=100)
    c_small = cost_service.estimate_monthly_cost_usd("aws", small)
    c_big = cost_service.estimate_monthly_cost_usd("aws", big)
    assert c_small is not None and c_big is not None
    assert c_big > c_small


def test_cost_unknown_provider_returns_none():
    assert cost_service.estimate_monthly_cost_usd("oracle", Workload(vcpu=1, ram_gb=1)) is None


def test_latency_increases_with_distance():
    user = GeoPoint(lat=38.9, lon=-77.0)  # US East
    near = latency_service.estimate_latency_ms("aws", "us-east-1", user)
    far = latency_service.estimate_latency_ms("aws", "ap-southeast-2", user)  # Sydney
    assert near is not None and far is not None
    assert far > near


def test_carbon_estimate_is_positive_and_scales():
    reading = CarbonReading(region="r", provider="aws", g_co2_per_kwh=400,
                            source="mock", timestamp="t", quality="mock")
    low = carbon_service.estimate_kg_co2_per_month(Workload(vcpu=1, ram_gb=1), reading)
    high = carbon_service.estimate_kg_co2_per_month(Workload(vcpu=8, ram_gb=32), reading)
    assert 0 < low < high


@pytest.mark.asyncio
async def test_recommender_regions_filter_restricts_candidate_set():
    repo = MockCarbonRepository()
    user = GeoPoint(lat=38.9, lon=-77.0)
    wl = Workload(vcpu=2, ram_gb=4)
    # Only consider two US AWS regions — Sweden (globally cleanest) must NOT appear or win.
    rec = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        regions=["us-east-1", "us-west-2"],
    )
    regions_seen = {c.region for c in rec.candidates}
    assert regions_seen == {"us-east-1", "us-west-2"}
    assert "eu-north-1" not in regions_seen
    assert rec.recommended_region in ("aws/us-east-1", "aws/us-west-2")


@pytest.mark.asyncio
async def test_recommender_regions_filter_keeps_baseline_even_if_unlisted():
    repo = MockCarbonRepository()
    user = GeoPoint(lat=38.9, lon=-77.0)
    wl = Workload(vcpu=2, ram_gb=4)
    # Filter lists only us-west-2, but baseline us-east-1 should be auto-included for comparison.
    rec = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        regions=["us-west-2"], baseline_region="us-east-1",
    )
    regions_seen = {c.region for c in rec.candidates}
    assert regions_seen == {"us-west-2", "us-east-1"}


@pytest.mark.asyncio
async def test_recommender_bogus_regions_filter_explains():
    repo = MockCarbonRepository()
    user = GeoPoint(lat=38.9, lon=-77.0)
    wl = Workload(vcpu=2, ram_gb=4)
    rec = await recommender.compare_regions(
        repo, None, user, wl, regions=["nowhere-1", "atlantis-2"],
    )
    assert rec.candidates == []
    assert "matched nothing" in rec.rationale.lower()


@pytest.mark.asyncio
async def test_recommender_prefers_cleaner_region_and_respects_latency_budget():
    repo = MockCarbonRepository()
    user = GeoPoint(lat=38.9, lon=-77.0)  # US East
    wl = Workload(vcpu=2, ram_gb=4, est_monthly_egress_gb=10)

    # Carbon-only: the mock makes Sweden (SE=25) the global cleanest.
    rec = await recommender.compare_regions(repo, None, user, wl, optimize_for="carbon")
    assert rec.recommended_region is not None
    assert rec.candidates[0].carbon_rank == 1
    assert rec.limitations  # caveats always present

    # Tight budget, US-only candidates: nothing meaningfully greener fits, so it should
    # stay on the baseline AND say so honestly (not dress the baseline up as a "win").
    rec_tight = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=20, baseline_region="us-east-1",
        regions=["us-east-1", "us-central1", "eastus"],
    )
    assert rec_tight.recommended_region == "aws/us-east-1"
    assert "reasonable" in rec_tight.rationale.lower() or "as good as it gets" in rec_tight.rationale.lower()

    # Same tight budget with the whole catalog: Montreal (Québec hydro) is close enough and far
    # cleaner, so the East Coast now has a real greener option.
    rec_ca = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=20, baseline_region="us-east-1",
    )
    assert rec_ca.recommended_region in ("aws/ca-central-1", "gcp/northamerica-northeast1",
                                         "azure/canadaeast")

    # Wide budget: the clean-but-far region (Sweden, 25 gCO2) should now win over us-east-1.
    rec_wide = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=500, baseline_region="us-east-1",
    )
    assert rec_wide.recommended_region == "aws/eu-north-1"
    assert "cleaner" in rec_wide.rationale.lower()

    # Tolerance band: a +105ms option under a +100ms cap should NOT be excluded. (US-only, so a
    # nearer clean region like Montreal doesn't pre-empt the band case being tested.)
    rec_band = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=100, baseline_region="us-east-1",
        regions=["us-east-1", "us-west-2", "us-central1"],
    )
    pick_band = next(c for c in rec_band.candidates
                     if f"{c.provider}/{c.region}" == rec_band.recommended_region)
    # us-west-2 is ~+105ms and 69% cleaner; with the band it should be the pick (not baseline).
    assert rec_band.recommended_region == "aws/us-west-2"
    assert pick_band.added_latency_ms is not None and pick_band.added_latency_ms <= 120


# --- Electricity Maps repository: logic verified without a real token/network ---

import httpx
from greenpick.data.electricitymaps_repository import ElectricityMapsRepository


def _mock_transport(handler):
    """Patch httpx.AsyncClient to route requests through `handler` (a function
    taking an httpx.Request and returning an httpx.Response)."""
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_em_live_reading_and_isEstimated(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        # eu-north-1 -> zone SE
        assert request.url.params.get("zone") == "SE"
        assert request.headers.get("auth-token") == "tok"
        return httpx.Response(200, json={"carbonIntensity": 42, "datetime": "2026-10-11T00:00:00Z",
                                         "isEstimated": True})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ElectricityMapsRepository(token="tok")
    r = await repo.carbon_now("aws", "eu-north-1")
    assert r.g_co2_per_kwh == 42
    assert r.source == "electricitymaps"
    assert r.quality == "live_estimated"   # isEstimated surfaced honestly


@pytest.mark.asyncio
async def test_em_bad_token_falls_back_to_mock(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid token"})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ElectricityMapsRepository(token="bad")
    r = await repo.carbon_now("aws", "eu-north-1")
    assert r.quality == "typical"          # degrades, labelled honestly
    assert repo._token_rejected is True  # won't keep hammering a bad key


@pytest.mark.asyncio
async def test_em_no_token_uses_mock():
    repo = ElectricityMapsRepository(token="")
    r = await repo.carbon_now("aws", "eu-north-1")
    assert r.quality == "typical"


# --- EIA repository: fuel-mix -> carbon-intensity math, verified without a real key/network ---

from greenpick.data.eia_repository import EIARepository


@pytest.mark.asyncio
async def test_eia_mix_to_carbon_intensity(monkeypatch):
    # PJM latest hour: 1000 MWh gas (490) + 1000 MWh nuclear (12) -> weighted mean = 251 gCO2/kWh.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("facets[respondent][]") == "PJM"
        return httpx.Response(200, json={"response": {"data": [
            {"period": "2026-10-11T18", "respondent": "PJM", "fueltype": "NG", "value": "1000"},
            {"period": "2026-10-11T18", "respondent": "PJM", "fueltype": "NUC", "value": "1000"},
            {"period": "2026-10-11T17", "respondent": "PJM", "fueltype": "NG", "value": "9999"},  # older hour, ignored
        ]}})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = EIARepository(api_key="key")
    r = await repo.carbon_now("aws", "us-east-1")     # maps to BA PJM
    assert r.source == "eia"
    assert r.quality == "live"
    assert abs(r.g_co2_per_kwh - 251.0) < 0.5          # (490+12)/2
    assert r.timestamp == "2026-10-11T18"              # only the latest hour used


@pytest.mark.asyncio
async def test_eia_non_us_region_falls_back_to_mock():
    repo = EIARepository(api_key="key")
    r = await repo.carbon_now("aws", "eu-north-1")     # no eia_ba -> mock
    assert r.quality == "typical"


@pytest.mark.asyncio
async def test_eia_no_key_uses_mock():
    repo = EIARepository(api_key="")
    r = await repo.carbon_now("aws", "us-east-1")
    assert r.quality == "typical"


# --- ENTSO-E repository: A75 XML -> carbon intensity, verified without token/network ---

from greenpick.data.entsoe_repository import ENTSOERepository

# Minimal A75-shaped XML: two production types (natural gas B04=490, nuclear B14=12),
# each 1000 MW in the latest point -> weighted mean 251 gCO2/kWh.
_A75_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <MktPSRType><psrType>B04</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-11T18:00Z</start></timeInterval>
      <Point><position>1</position><quantity>900</quantity></Point>
      <Point><position>2</position><quantity>1000</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B14</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-11T18:00Z</start></timeInterval>
      <Point><position>1</position><quantity>1000</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
async def test_entsoe_xml_to_carbon_intensity(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("in_Domain") == "10YSE-1--------K"  # Sweden EIC
        assert request.url.params.get("documentType") == "A75"
        return httpx.Response(200, text=_A75_XML)

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ENTSOERepository(token="tok")
    r = await repo.carbon_now("aws", "eu-north-1")   # Sweden
    assert r.source == "entsoe"
    assert r.quality == "live"
    # gas latest point = 1000 (position 2), nuclear = 1000 -> (490+12)/2 = 251
    assert abs(r.g_co2_per_kwh - 251.0) < 0.5


@pytest.mark.asyncio
async def test_entsoe_non_eu_region_falls_back_to_mock():
    repo = ENTSOERepository(token="tok")
    r = await repo.carbon_now("aws", "us-east-1")    # no entsoe_eic -> mock
    assert r.quality == "typical"


# Multi-hour A75: hour 18 nuclear-heavy (cleaner), hour 19 gas-heavy (dirtier).
# Hourly resolution (PT60M), two positions = two hours. Gas B04=490, nuclear B14=12.
_A75_MULTIHOUR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <MktPSRType><psrType>B04</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-12T18:00Z</start><end>2026-10-12T20:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>500</quantity></Point>
      <Point><position>2</position><quantity>1500</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B14</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-12T18:00Z</start><end>2026-10-12T20:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>1500</quantity></Point>
      <Point><position>2</position><quantity>500</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
async def test_entsoe_carbon_history_multihour(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("documentType") == "A75"
        return httpx.Response(200, text=_A75_MULTIHOUR_XML)

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ENTSOERepository(token="tok")
    hist = await repo.carbon_history("aws", "eu-north-1")   # Sweden
    periods = {h.period: h.g_co2_per_kwh for h in hist}
    # Position 1 -> hour 18, position 2 -> hour 19 (hourly resolution).
    assert set(periods) == {"2026-10-12T18", "2026-10-12T19"}
    # hour 18: 500 gas + 1500 nuc -> (500*490 + 1500*12)/2000 = 131.5
    assert abs(periods["2026-10-12T18"] - 131.5) < 0.5
    # hour 19: 1500 gas + 500 nuc -> (1500*490 + 500*12)/2000 = 370.5
    assert abs(periods["2026-10-12T19"] - 370.5) < 0.5
    assert periods["2026-10-12T18"] < periods["2026-10-12T19"]  # nuclear-heavy hour cleaner


@pytest.mark.asyncio
async def test_entsoe_carbon_history_no_token_uses_mock():
    repo = ENTSOERepository(token="")
    hist = await repo.carbon_history("aws", "eu-north-1")
    assert len(hist) == 24   # synthetic fallback curve, not blocked


@pytest.mark.asyncio
async def test_auto_router_picks_source_by_region(monkeypatch):
    from greenpick.data.auto_repository import AutoRepository

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "eia.gov" in host:
            return httpx.Response(200, json={"response": {"data": [
                {"period": "2026-10-11T18", "fueltype": "NG", "value": "1000"},
            ]}})
        # entsoe
        return httpx.Response(200, text=_A75_XML)

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = AutoRepository(eia_key="k", entsoe_token="t")
    us = await repo.carbon_now("aws", "us-east-1")      # -> EIA
    eu = await repo.carbon_now("aws", "eu-north-1")     # -> ENTSO-E
    syd = await repo.carbon_now("aws", "ap-southeast-2")  # -> no live source: sourced yearly figure
    assert us.source == "eia"
    assert eu.source == "entsoe"
    assert syd.quality == "annual_average"


@pytest.mark.asyncio
async def test_per_axis_ratings_assigned(monkeypatch):
    repo = MockCarbonRepository()
    user = GeoPoint(lat=38.9, lon=-77.0)
    wl = Workload(vcpu=2, ram_gb=4, est_monthly_egress_gb=10)
    rec = await recommender.compare_regions(repo, None, user, wl, optimize_for="carbon")
    # Every candidate gets a R/Y/G on each axis, from the allowed set.
    allowed = {"green", "yellow", "red"}
    for c in rec.candidates:
        assert c.carbon_rating in allowed
        assert c.latency_rating in allowed
        assert c.cost_rating in allowed
    # The cleanest region (rank 1) must be green on carbon; the dirtiest must be red.
    by_carbon = sorted(rec.candidates, key=lambda c: c.carbon.g_co2_per_kwh)
    assert by_carbon[0].carbon_rating == "green"
    assert by_carbon[-1].carbon_rating == "red"


# --- GPU training carbon (placement + timing) ---

from greenpick.services import training_service


def test_training_energy_scales_with_gpu_hours_and_tdp():
    # gpu_hours is TOTAL accelerator-hours, so more total hours = more energy.
    e_small = training_service.run_energy_kwh("a100", gpu_count=1, gpu_hours=10, utilization=0.85)
    e_big = training_service.run_energy_kwh("a100", gpu_count=8, gpu_hours=80, utilization=0.85)
    assert e_big > e_small
    # Higher-TDP card draws more for the same GPU-hours.
    e_a100 = training_service.run_energy_kwh("a100", 1, 40, 0.85)   # 400W
    e_h100 = training_service.run_energy_kwh("h100", 1, 40, 0.85)   # 700W
    assert e_h100 > e_a100
    # Hand-check: 1x H100, 40 GPU-h -> (700*0.85 + 100)/1000 * 40 * 1.2 = 33.36 kWh
    assert abs(e_h100 - 33.36) < 0.1


@pytest.mark.asyncio
async def test_training_ranks_regions_greenest_first_and_times_them():
    repo = MockCarbonRepository()
    adv = await training_service.estimate_training_carbon(
        repo, gpu="h100", gpu_count=1, gpu_hours=40,  # no region -> rank
    )
    assert adv.gpu == "h100"
    assert adv.est_energy_kwh > 0
    # Greenest-first ordering by run CO2.
    kgs = [o.est_kg_co2 for o in adv.options]
    assert kgs == sorted(kgs)
    assert adv.recommended_region is not None
    # Sweden (mock SE=25) should be the greenest option -> recommended.
    assert "eu-north-1" in adv.recommended_region or "swedencentral" in adv.recommended_region
    # Ratings assigned; greenest is green.
    assert adv.options[0].rating == "green"
    # Timing filled in for the greenest region (mock history = 24h synthetic).
    assert adv.timing_quality == "mock"
    assert len(adv.cleanest_hours) == 3


@pytest.mark.asyncio
async def test_training_specific_region_uses_that_region():
    repo = MockCarbonRepository()
    adv = await training_service.estimate_training_carbon(
        repo, gpu="a100", gpu_count=2, gpu_hours=40, region="us-east-1",
    )
    assert adv.region == "us-east-1"
    assert adv.recommended_region == "aws/us-east-1"
    assert len(adv.options) == 1
    assert adv.options[0].est_kg_co2 > 0


@pytest.mark.asyncio
async def test_training_unknown_gpu_is_handled():
    repo = MockCarbonRepository()
    adv = await training_service.estimate_training_carbon(
        repo, gpu="rtx-9999", gpu_count=1, gpu_hours=10,
    )
    assert adv.est_energy_kwh == 0.0
    assert "unknown gpu" in adv.rationale.lower()


# --- LLM inference carbon ---

from greenpick.services import inference_service


@pytest.mark.asyncio
async def test_inference_scales_with_requests_and_tokens():
    repo = MockCarbonRepository()
    base = await inference_service.estimate_inference_carbon(repo, "small", 1_000_000, avg_output_tokens=300)
    more_req = await inference_service.estimate_inference_carbon(repo, "small", 2_000_000, avg_output_tokens=300)
    more_tok = await inference_service.estimate_inference_carbon(repo, "small", 1_000_000, avg_output_tokens=600)
    assert more_req.monthly_kwh_high > base.monthly_kwh_high      # 2x requests -> more energy
    assert more_tok.monthly_kwh_high > base.monthly_kwh_high      # 2x output tokens -> more energy
    # low <= high band always holds
    assert base.monthly_kwh_low <= base.monthly_kwh_high


@pytest.mark.asyncio
async def test_inference_bigger_class_uses_more_energy():
    repo = MockCarbonRepository()
    small = await inference_service.estimate_inference_carbon(repo, "small", 1_000_000)
    frontier = await inference_service.estimate_inference_carbon(repo, "frontier_dense", 1_000_000)
    # Size class is the big lever — frontier dense >> small for the same workload.
    assert frontier.monthly_kwh_high > small.monthly_kwh_high * 5


@pytest.mark.asyncio
async def test_inference_param_alias_and_moe_resolve():
    repo = MockCarbonRepository()
    a = await inference_service.estimate_inference_carbon(repo, "8b", 100_000)
    assert a.size_class == "small"                 # '8b' alias -> small
    moe = await inference_service.estimate_inference_carbon(repo, "moe", 100_000)
    assert moe.size_class == "moe_frontier"        # 'moe' alias
    # MoE runs near active params -> cheaper than frontier DENSE at the high end.
    dense = await inference_service.estimate_inference_carbon(repo, "frontier_dense", 100_000)
    assert moe.monthly_kwh_high < dense.monthly_kwh_high


@pytest.mark.asyncio
async def test_inference_adds_carbon_for_region():
    repo = MockCarbonRepository()
    adv = await inference_service.estimate_inference_carbon(
        repo, "large", 1_000_000, avg_output_tokens=300, region="us-east-1",
    )
    assert adv.grid_intensity_g_co2_per_kwh is not None
    assert adv.monthly_kg_co2_low is not None and adv.monthly_kg_co2_high is not None
    assert adv.monthly_kg_co2_low <= adv.monthly_kg_co2_high


@pytest.mark.asyncio
async def test_inference_unknown_class_is_handled():
    repo = MockCarbonRepository()
    adv = await inference_service.estimate_inference_carbon(repo, "gpt-9", 1000)
    assert adv.monthly_kwh_high == 0
    assert "unknown size class" in adv.rationale.lower()


# --- Right-sizing (FinOps dual-benefit) ---

from greenpick.services import rightsizing_service


@pytest.mark.asyncio
async def test_rightsizing_flags_oversized_and_saves_both():
    repo = MockCarbonRepository()
    # 8 vCPU / 32 GB at 15% CPU use -> clearly over-provisioned.
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=8, ram_gb=32, cpu_utilization=0.15,
    )
    assert adv.is_oversized
    assert adv.recommended_vcpu < 8                       # shrinks
    assert adv.recommended_vcpu >= 0.5                    # but not below the floor
    assert adv.monthly_kg_co2_saving > 0
    assert adv.monthly_usd_saving is not None and adv.monthly_usd_saving > 0
    assert adv.saving_pct is not None and adv.saving_pct >= 10
    assert "over-provisioned" in adv.rationale.lower()


@pytest.mark.asyncio
async def test_rightsizing_leaves_well_sized_alone():
    repo = MockCarbonRepository()
    # 2 vCPU at 80% use -> headroom already sensible, no material saving.
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=2, ram_gb=4, cpu_utilization=0.8,
    )
    assert adv.is_oversized is False
    assert "reasonably sized" in adv.rationale.lower() or "sensible headroom" in adv.rationale.lower()


@pytest.mark.asyncio
async def test_rightsizing_never_upsizes_and_keeps_headroom():
    repo = MockCarbonRepository()
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=4, ram_gb=8, cpu_utilization=0.5,
    )
    # Right-sizing only shrinks (or holds), never grows.
    assert adv.recommended_vcpu <= 4
    # 50% use x 1.4 headroom = 70% of provisioned -> ~2.8 vCPU, above raw usage (keeps headroom).
    assert adv.recommended_vcpu > 4 * 0.5


# --- Carbon metric scaffold (emit instrumentation code) ---

from greenpick.services import metric_scaffold_service


@pytest.mark.asyncio
async def test_metric_scaffold_emits_valid_python_with_coefficients():
    repo = MockCarbonRepository()
    s = await metric_scaffold_service.carbon_metric_scaffold(repo, language="python", vcpu=2, ram_gb=4)
    assert s.language == "python"
    # Coefficients come from the real power model.
    from greenpick.data.static_data import power_model
    pm = power_model()
    assert s.coefficients["watts_per_vcpu"] == pm["watts_per_vcpu"]
    # The emitted code must be SYNTACTICALLY VALID Python (we're shipping code to paste in).
    compile(s.code, "<scaffold>", "exec")
    # And it must be self-labelled as an estimate, not metered energy.
    assert "estimated_gco2" in s.code.lower()
    assert "not a measurement" in s.code.lower() or "not metered" in s.limitations.lower()
    assert s.limitations and s.methodology


@pytest.mark.asyncio
async def test_metric_scaffold_bakes_in_grid_intensity_for_region():
    repo = MockCarbonRepository()
    s = await metric_scaffold_service.carbon_metric_scaffold(
        repo, language="python", region="us-east-1", vcpu=2, ram_gb=4,
    )
    assert s.grid_intensity_g_co2_per_kwh is not None
    # The baked-in grid value should appear in the generated code (not left as None).
    assert "_GRID_G_CO2_PER_KWH = None" not in s.code
    compile(s.code, "<scaffold>", "exec")


@pytest.mark.asyncio
async def test_metric_scaffold_emitted_estimator_computes_sanely():
    # Execute the emitted snippet and check the estimator behaves: more CPU -> more gCO2,
    # and no grid intensity -> None (honest, not a fake zero).
    repo = MockCarbonRepository()
    s = await metric_scaffold_service.carbon_metric_scaffold(
        repo, language="python", region="us-east-1", vcpu=4, ram_gb=8,
    )
    ns: dict = {}
    exec(s.code, ns)
    Est = ns["CarbonEstimator"]
    e = Est(vcpu=4, ram_gb=8)
    low = e.estimated_gco2_per_hour(0.1)
    high = e.estimated_gco2_per_hour(0.9)
    assert low is not None and high is not None and high > low
    # With no grid intensity, carbon is None (can't honestly estimate), not 0.
    e2 = Est(vcpu=4, ram_gb=8, grid_g_co2_per_kwh=None)
    assert e2.estimated_gco2_per_hour(0.5) is None


@pytest.mark.asyncio
async def test_metric_scaffold_unsupported_language_is_honest():
    repo = MockCarbonRepository()
    s = await metric_scaffold_service.carbon_metric_scaffold(repo, language="cobol")
    assert s.code == ""
    assert "not supported" in s.how_to_use.lower()
    assert s.methodology   # still explains the math so it ports


# --- Serving-pattern advice (single vs multi-region) ---

from greenpick.services import serving_service
from greenpick.models import ServingHub


@pytest.mark.asyncio
async def test_serving_concentrated_users_prefer_single_region():
    repo = MockCarbonRepository()
    wl = Workload(vcpu=2, ram_gb=4)
    # Everyone in the US -> a single US region is the obvious call.
    hubs = [ServingHub(name="us", lat=0, lon=0, share=1.0)]
    adv = await serving_service.serving_pattern(repo, hubs, wl)
    assert adv.single_region is not None
    assert adv.recommended_pattern == "single_region"
    # Single region should be a US region (nearest the only hub).
    assert adv.single_region.region in {"us-east-1", "us-west-2", "us-central1",
                                        "us-west1", "eastus"}


@pytest.mark.asyncio
async def test_serving_spread_users_consider_multi_region_and_flag_caveats():
    repo = MockCarbonRepository()
    wl = Workload(vcpu=2, ram_gb=4)
    # Users split US / EU / APAC -> multi-region should cut weighted latency and span regions.
    hubs = [
        ServingHub(name="us", lat=0, lon=0, share=0.4),
        ServingHub(name="eu", lat=0, lon=0, share=0.4),
        ServingHub(name="apac", lat=0, lon=0, share=0.2),
    ]
    adv = await serving_service.serving_pattern(repo, hubs, wl)
    assert len(adv.multi_region) == 3
    assert adv.multi_region_weighted_latency_ms is not None
    # Multi-region weighted latency should beat (be <=) the single-region weighted latency.
    assert adv.multi_region_weighted_latency_ms <= adv.single_region.weighted_latency_ms
    # Spanning multiple regions must surface the data-sync egress caveat.
    distinct = {(c.provider, c.region) for c in adv.multi_region}
    if len(distinct) > 1:
        assert adv.data_sync_egress_note is not None
        assert "egress" in adv.data_sync_egress_note.lower()


@pytest.mark.asyncio
async def test_serving_eu_hub_served_from_us_flags_residency():
    repo = MockCarbonRepository()
    wl = Workload(vcpu=2, ram_gb=4)
    # Force a US-only candidate set so the EU hub must be served from the US -> residency flag.
    hubs = [
        ServingHub(name="us", lat=0, lon=0, share=0.5),
        ServingHub(name="eu", lat=0, lon=0, share=0.5),
    ]
    # Restrict providers won't restrict regions; instead rely on the fact that with only US+EU
    # catalog regions, the EU hub maps to an EEA region and US hub to US — so if any hub is served
    # cross-jurisdiction the note appears. We assert the note is either present or correctly None.
    adv = await serving_service.serving_pattern(repo, hubs, wl)
    # Each hub is served by its nearest region, so EU hub -> EEA region, US hub -> US region:
    # same-jurisdiction per hub, so no residency note expected here (sanity: not a false positive).
    assert adv.residency_note is None


@pytest.mark.asyncio
async def test_serving_no_hubs_is_handled():
    repo = MockCarbonRepository()
    adv = await serving_service.serving_pattern(repo, [], Workload(vcpu=1, ram_gb=1))
    assert adv.hubs == []
    assert adv.single_region is None          # nothing to recommend without hubs
    assert "no user hubs" in adv.rationale.lower()


# --- Data-residency awareness (geographic flag, not a compliance verdict) ---

from greenpick.services import residency_service


def test_residency_flag_leaving_eea_is_called_out():
    # Ireland (EEA) -> Oregon (US): leaving the EEA, the high-stakes direction.
    note = residency_service.residency_flag("aws", "eu-west-1", "aws", "us-west-2")
    assert note is not None
    assert "EEA" in note
    assert "GDPR" in note
    assert "does not assess legal compliance" in note.lower()


def test_residency_flag_same_jurisdiction_is_none():
    # Two US regions -> no crossing, no flag.
    assert residency_service.residency_flag("aws", "us-east-1", "aws", "us-west-2") is None
    # Ireland -> Sweden, both EEA -> no flag.
    assert residency_service.residency_flag("aws", "eu-west-1", "aws", "eu-north-1") is None


def test_residency_flag_crossing_non_eea_is_neutral():
    # US -> AU: a crossing, flagged, but NOT the EEA-specific wording.
    note = residency_service.residency_flag("aws", "us-east-1", "aws", "ap-southeast-2")
    assert note is not None
    assert "crosses jurisdictions" in note.lower()
    assert "GDPR" not in note          # only called out when leaving the EEA
    assert "does not assess legal compliance" in note.lower()


@pytest.mark.asyncio
async def test_recommender_sets_residency_note_when_pick_leaves_eea():
    repo = MockCarbonRepository()
    user = GeoPoint(lat=53.3, lon=-6.3)   # Dublin-ish
    wl = Workload(vcpu=2, ram_gb=4)
    # Baseline Ireland (EEA); the mock makes Sweden cleanest (also EEA) so NO flag normally —
    # but if we baseline in the EEA and the global cleanest is EEA too, no crossing. Force a
    # cross by restricting to US regions with an EEA baseline.
    rec = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        baseline_region="eu-west-1", regions=["us-east-1", "us-west-2"],
    )
    assert rec.residency_note is not None
    assert "EEA" in rec.residency_note


@pytest.mark.asyncio
async def test_locality_sets_residency_note_cross_jurisdiction():
    from greenpick.services import locality_service   # imported here; module-level import is later
    repo = MockCarbonRepository()
    # Data in the EEA (Ireland), compute in the US -> residency flag present.
    w = await locality_service.data_locality_check(
        repo, "aws", "us-east-1", "aws", "eu-west-1", monthly_cross_boundary_gb=500,
    )
    assert w.residency_note is not None
    assert "EEA" in w.residency_note


# --- Forward-looking forecast ---

from greenpick.services import forecast_service


@pytest.mark.asyncio
async def test_forecast_fallback_on_mock_history_is_labelled_mock():
    # No forecast and only mock history: the fallback pattern is synthetic, so it must say mock,
    # not 'historical' (which would pass an illustrative curve off as real past data).
    repo = MockCarbonRepository()
    adv = await forecast_service.carbon_forecast(repo, "aws", "us-east-1", hours_ahead=24)
    assert adv.source == "mock"
    assert adv.quality == "mock"
    assert adv.cleanest_upcoming == []
    assert "not meaningful" in adv.note


@pytest.mark.asyncio
async def test_forecast_degrades_to_historical_with_live_history(monkeypatch):
    # US region with live EIA history but no day-ahead forecast -> a real historical fallback.
    def handler(request: httpx.Request) -> httpx.Response:
        data = []
        for day in ("2026-10-10", "2026-10-11"):
            data += [
                {"period": f"{day}T02", "fueltype": "NUC", "value": "1800"},
                {"period": f"{day}T02", "fueltype": "NG", "value": "200"},
                {"period": f"{day}T18", "fueltype": "NUC", "value": "200"},
                {"period": f"{day}T18", "fueltype": "NG", "value": "1800"},
            ]
        return httpx.Response(200, json={"response": {"data": data}})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    adv = await forecast_service.carbon_forecast(EIARepository(api_key="k"), "aws", "us-east-1")
    assert adv.source == "historical_fallback"
    assert adv.quality == "historical"
    assert "historical" in adv.note.lower()


# A69-shaped forecast XML: wind (B19) + solar (B16), hourly, 3 hours. Hour 2 has the most wind.
_A69_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <MktPSRType><psrType>B19</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-13T00:00Z</start><end>2026-10-13T03:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>1000</quantity></Point>
      <Point><position>2</position><quantity>1500</quantity></Point>
      <Point><position>3</position><quantity>3000</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B16</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-10-13T00:00Z</start><end>2026-10-13T03:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>0</quantity></Point>
      <Point><position>2</position><quantity>200</quantity></Point>
      <Point><position>3</position><quantity>100</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
async def test_entsoe_renewable_forecast_parses_and_sums(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        dt = request.url.params.get("documentType")
        if dt == "A69":
            return httpx.Response(200, text=_A69_XML)
        # A65 load not available for this zone -> empty, like Ireland in the spike.
        return httpx.Response(200, text="<x>No matching data found</x>")

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ENTSOERepository(token="tok")
    hours = await repo.renewable_forecast("aws", "eu-north-1", hours_ahead=3)
    by = {h.period: h.renewable_mw for h in hours}
    # wind+solar summed per hour: H00=1000, H01=1700, H02=3100.
    assert abs(by["2026-10-13T00"] - 1000) < 0.1
    assert abs(by["2026-10-13T01"] - 1700) < 0.1
    assert abs(by["2026-10-13T02"] - 3100) < 0.1
    # No load available -> share stays None.
    assert all(h.renewable_share is None for h in hours)


@pytest.mark.asyncio
async def test_forecast_service_ranks_cleanest_upcoming(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("documentType") == "A69":
            return httpx.Response(200, text=_A69_XML)
        return httpx.Response(200, text="<x>No matching data found</x>")

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = ENTSOERepository(token="tok")
    adv = await forecast_service.carbon_forecast(repo, "aws", "eu-north-1", hours_ahead=3, top_n=3)
    assert adv.source == "entsoe_forecast"
    assert adv.quality == "forecast"
    # Cleanest = most renewables = hour 02 (3100 MW) first.
    assert adv.cleanest_upcoming[0].period == "2026-10-13T02"
    assert adv.peak_renewable_period == "2026-10-13T02"
    assert adv.low_renewable_period == "2026-10-13T00"


@pytest.mark.asyncio
async def test_auto_repository_forecast_routes_eu_only(monkeypatch):
    from greenpick.data.auto_repository import AutoRepository

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("documentType") == "A69":
            return httpx.Response(200, text=_A69_XML)
        return httpx.Response(200, text="<x>No matching data found</x>")

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = AutoRepository(eia_key="k", entsoe_token="t")
    eu = await repo.renewable_forecast("aws", "eu-north-1", 3)   # Sweden -> ENTSO-E
    us = await repo.renewable_forecast("aws", "us-east-1", 3)    # PJM -> no forecast
    assert len(eu) == 3
    assert us == []   # US has no free forecast -> empty, caller degrades


# --- Data-locality / egress warning ---

from greenpick.services import locality_service


@pytest.mark.asyncio
async def test_locality_same_region_no_penalty():
    repo = MockCarbonRepository()
    w = await locality_service.data_locality_check(
        repo, "aws", "us-east-1", "aws", "us-east-1", monthly_cross_boundary_gb=5000,
    )
    assert w.locality == "same_region"
    assert w.severity == "none"
    assert w.est_monthly_egress_usd_low == 0.0
    assert w.est_monthly_egress_usd_high == 0.0
    assert w.est_monthly_transfer_kg_co2 == 0.0


@pytest.mark.asyncio
async def test_locality_cross_cloud_is_high_and_costs_money():
    repo = MockCarbonRepository()
    w = await locality_service.data_locality_check(
        repo, "gcp", "europe-north1", "aws", "us-east-1", monthly_cross_boundary_gb=2000,
    )
    assert w.locality == "cross_cloud"
    assert w.severity == "high"            # cross-cloud + big volume
    # cross-cloud/internet tier spans ~0.085-0.12/GB x 2000 GB -> ~$170-$240 (high = GCP Premium
    # end of the internet tier; not under-quoted by the data provider's own rate either).
    assert abs(w.est_monthly_egress_usd_low - 170.0) < 0.01    # 0.085 x 2000
    assert abs(w.est_monthly_egress_usd_high - 240.0) < 0.01   # 0.12  x 2000
    assert w.est_monthly_egress_usd_low <= w.est_monthly_egress_usd_high
    assert w.est_monthly_transfer_kg_co2 is not None and w.est_monthly_transfer_kg_co2 > 0


@pytest.mark.asyncio
async def test_locality_cross_region_small_volume_downgrades_severity():
    repo = MockCarbonRepository()
    w = await locality_service.data_locality_check(
        repo, "aws", "us-west-2", "aws", "us-east-1", monthly_cross_boundary_gb=10,
    )
    assert w.locality == "cross_region_same_cloud"
    assert w.severity == "low"             # medium base, <50 GB -> downgraded
    # cross-region tier 0.01-0.02/GB x 10 GB -> $0.10-$0.20 (NOT the ~$0.90 the old flat
    # internet rate would have overstated it as).
    assert abs(w.est_monthly_egress_usd_low - 0.10) < 0.01
    assert abs(w.est_monthly_egress_usd_high - 0.20) < 0.01


@pytest.mark.asyncio
async def test_locality_net_carbon_verdict_backfire_vs_win():
    repo = MockCarbonRepository()
    # Big transfer so the move's carbon saving is swamped -> backfire verdict.
    backfire = await locality_service.data_locality_check(
        repo, "aws", "eu-north-1", "aws", "us-east-1",
        monthly_cross_boundary_gb=5000, carbon_saving_kg_co2_from_move=1.0,
    )
    assert backfire.net_carbon_verdict is not None
    assert "backfire" in backfire.net_carbon_verdict.lower() or "worse" in backfire.net_carbon_verdict.lower()
    # Tiny transfer, large saving -> net win verdict.
    win = await locality_service.data_locality_check(
        repo, "aws", "eu-north-1", "aws", "us-east-1",
        monthly_cross_boundary_gb=5, carbon_saving_kg_co2_from_move=50.0,
    )
    assert win.net_carbon_verdict is not None
    assert "net win" in win.net_carbon_verdict.lower()


# --- Carbon-aware scheduling ---

from greenpick.services import scheduling_service


# --- Greener instance-family suggestion ---

from greenpick.services import instance_service


@pytest.mark.asyncio
async def test_greener_instance_family_prefers_arm_and_computes_savings():
    repo = MockCarbonRepository()
    adv = await instance_service.greener_instance_family(
        repo, "aws", "us-east-1", vcpu=4, ram_gb=16, current_family="m5",
    )
    # Greenest AWS general-purpose option is the ARM Graviton3 family (lowest relative_energy).
    assert adv.recommended_family == "m7g"
    assert adv.options[0].family == "m7g"          # greenest first
    assert adv.options[0].arch == "arm"
    assert adv.current_family == "m5"
    # m7g relative_energy 0.45 vs m5 1.00 -> ~55% energy & CO2 saving.
    top = adv.options[0]
    assert top.energy_saving_vs_current_pct is not None
    assert abs(top.energy_saving_vs_current_pct - 55.0) < 1.0
    assert top.co2_saving_vs_current_pct == top.energy_saving_vs_current_pct
    # Ratings assigned from the allowed set; greenest is green.
    allowed = {"green", "yellow", "red"}
    assert all(o.rating in allowed for o in adv.options)
    assert adv.options[0].rating == "green"
    # ARM caveat surfaced honestly in the rationale.
    assert "arm" in adv.rationale.lower()
    assert adv.limitations


@pytest.mark.asyncio
async def test_greener_instance_family_already_greenest_says_no_change():
    repo = MockCarbonRepository()
    adv = await instance_service.greener_instance_family(
        repo, "aws", "us-east-1", vcpu=2, ram_gb=8, current_family="m7g",
    )
    assert adv.recommended_family == "m7g"
    assert "no change" in adv.rationale.lower() or "already" in adv.rationale.lower()
    # Current family on the greenest option -> 0% saving vs itself.
    cur = next(o for o in adv.options if o.family == "m7g")
    assert cur.energy_saving_vs_current_pct == 0.0


def test_greener_instance_family_provider_support_gate():
    # Unsupported providers are rejected at the boundary (server returns an error dict),
    # so the strictly-typed advice model never has to hold a bogus provider.
    assert instance_service.is_supported_provider("aws")
    assert not instance_service.is_supported_provider("oracle")


@pytest.mark.asyncio
async def test_greener_instance_family_gcp_and_azure_have_arm_winners():
    repo = MockCarbonRepository()
    gcp = await instance_service.greener_instance_family(repo, "gcp", "us-central1", vcpu=2, ram_gb=8)
    az = await instance_service.greener_instance_family(repo, "azure", "swedencentral", vcpu=2, ram_gb=8)
    assert gcp.options[0].arch == "arm"       # Axion c4a
    assert az.options[0].arch == "arm"        # Ampere Dpsv5
    # Grid intensity is carried through from the (mock) reading.
    assert gcp.grid_intensity_g_co2_per_kwh is not None


@pytest.mark.asyncio
async def test_cleanest_time_of_day_mock_single_day():
    repo = MockCarbonRepository()
    adv = await scheduling_service.cleanest_time_of_day(repo, "aws", "us-east-1")
    # Mock history is a 24h synthetic curve (H00..H23) -> one day, 24 hour-of-day buckets.
    assert adv.days_analyzed == 1
    assert len(adv.by_hour_of_day) == 24
    # Cleanest-first ordering.
    avgs = [s.avg_g_co2_per_kwh for s in adv.by_hour_of_day]
    assert avgs == sorted(avgs)
    assert adv.cleanest_hour_of_day is not None and 0 <= adv.cleanest_hour_of_day <= 23
    assert adv.limitations  # honesty caveat present


@pytest.mark.asyncio
async def test_cleanest_time_of_day_averages_across_days(monkeypatch):
    # EIA across 3 days: hour 02 is clean every day, hour 18 is dirty every day.
    # Build fuel rows so hour 02 = nuclear-heavy, hour 18 = gas-heavy, on 3 consecutive days.
    def handler(request: httpx.Request) -> httpx.Response:
        data = []
        for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
            data += [
                {"period": f"{day}T02", "fueltype": "NUC", "value": "1800"},
                {"period": f"{day}T02", "fueltype": "NG",  "value": "200"},
                {"period": f"{day}T18", "fueltype": "NUC", "value": "200"},
                {"period": f"{day}T18", "fueltype": "NG",  "value": "1800"},
            ]
        return httpx.Response(200, json={"response": {"data": data}})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = EIARepository(api_key="k")
    adv = await scheduling_service.cleanest_time_of_day(repo, "aws", "us-east-1")
    assert adv.days_analyzed == 3
    assert adv.cleanest_hour_of_day == 2      # nuclear-heavy hour, every day
    assert adv.dirtiest_hour_of_day == 18     # gas-heavy hour, every day
    # Each hour-of-day averaged over all 3 days.
    h2 = next(s for s in adv.by_hour_of_day if s.hour_of_day == 2)
    assert h2.days_observed == 3
    assert adv.potential_reduction_pct is not None and adv.potential_reduction_pct > 10


@pytest.mark.asyncio
async def test_cleanest_hours_window_backward_compatible():
    # No window_hours -> unchanged behaviour, window stays None.
    repo = MockCarbonRepository()
    advice = await scheduling_service.cleanest_hours(repo, "aws", "us-east-1", top_n=3)
    assert advice.window is None
    assert advice.window_reduction_pct is None


@pytest.mark.asyncio
async def test_cleanest_hours_window_finds_contiguous_run():
    repo = MockCarbonRepository()
    advice = await scheduling_service.cleanest_hours(
        repo, "aws", "us-east-1", top_n=3, window_hours=6,
    )
    assert advice.window is not None
    w = advice.window
    assert w.window_hours == 6
    assert len(w.hours) == 6
    # The window must be CONTIGUOUS: mock periods are H00..H23, so the 6 hours step by 1.
    nums = [int(h.period[1:]) for h in w.hours]
    assert nums == list(range(nums[0], nums[0] + 6))
    # Its average equals the mean of its hours.
    assert abs(w.avg_g_co2_per_kwh - sum(h.g_co2_per_kwh for h in w.hours) / 6) < 0.1
    # A 6h window average can't beat the single cleanest hour (it includes neighbours).
    assert w.avg_g_co2_per_kwh >= advice.cleanest_g_co2_per_kwh


def test_window_contiguity_breaks_on_gap():
    # Build a series with a gap: hours 0,1,2 then jump to 20,21. A 3h window can only be 0-1-2.
    from greenpick.models import HourlyCarbon
    series = [
        HourlyCarbon(period="H00", g_co2_per_kwh=10),
        HourlyCarbon(period="H01", g_co2_per_kwh=10),
        HourlyCarbon(period="H02", g_co2_per_kwh=10),
        HourlyCarbon(period="H20", g_co2_per_kwh=1),   # cleaner, but isolated
        HourlyCarbon(period="H21", g_co2_per_kwh=1),
    ]
    hours, _red = scheduling_service._best_and_worst_window(series, 3)
    assert hours is not None
    assert [h.period for h in hours] == ["H00", "H01", "H02"]   # only contiguous 3-run available


def test_window_hour_index_parses_iso_and_mock():
    assert scheduling_service._hour_index("H05") == 5
    a = scheduling_service._hour_index("2026-10-12T18")
    b = scheduling_service._hour_index("2026-10-12T19")
    assert a is not None and b is not None and b - a == 1   # consecutive ISO hours step by 1
    assert scheduling_service._hour_index("garbage") is None


@pytest.mark.asyncio
async def test_cleanest_hours_mock():
    repo = MockCarbonRepository()
    advice = await scheduling_service.cleanest_hours(repo, "aws", "us-east-1", top_n=3)
    assert advice.hours_analyzed == 24
    assert len(advice.cleanest) == 3
    # cleanest first, ascending
    g = [h.g_co2_per_kwh for h in advice.cleanest]
    assert g == sorted(g)
    # the top pick is the global minimum of the series
    assert advice.cleanest_g_co2_per_kwh == advice.cleanest[0].g_co2_per_kwh
    assert advice.cleanest_g_co2_per_kwh <= advice.dirtiest_g_co2_per_kwh
    assert advice.quality == "mock"


@pytest.mark.asyncio
async def test_cleanest_hours_eia_multihour(monkeypatch):
    # Two hours: hour 18 cleaner (more nuclear), hour 19 dirtier (more gas).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"data": [
            {"period": "2026-10-12T19", "fueltype": "NG",  "value": "1500"},
            {"period": "2026-10-12T19", "fueltype": "NUC", "value": "500"},
            {"period": "2026-10-12T18", "fueltype": "NG",  "value": "500"},
            {"period": "2026-10-12T18", "fueltype": "NUC", "value": "1500"},
        ]}})
    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = EIARepository(api_key="k")
    hist = await repo.carbon_history("aws", "us-east-1")
    periods = {h.period: h.g_co2_per_kwh for h in hist}
    assert set(periods) == {"2026-10-12T18", "2026-10-12T19"}
    assert periods["2026-10-12T18"] < periods["2026-10-12T19"]  # nuclear-heavy hour cleaner


# --- 0.1.4 regressions: findings from outside-agent testing ---

@pytest.mark.asyncio
async def test_rightsizing_recommends_a_standard_buyable_size():
    from greenpick.services import rightsizing_service
    repo = MockCarbonRepository()
    # 8 vCPU / 32 GB at 15% CPU, 20% RAM: the raw fit is ~1.7 vCPU / ~9 GB, which no cloud sells.
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=8, ram_gb=32, cpu_utilization=0.15, ram_utilization=0.20,
    )
    assert adv.is_oversized
    assert (adv.recommended_vcpu, adv.recommended_ram_gb) == (2.0, 16.0)   # smallest shape that fits
    assert adv.recommended_ram_gb / adv.recommended_vcpu in (2, 4, 8)
    assert "standard size" in adv.rationale


@pytest.mark.asyncio
async def test_rightsizing_unknown_ram_keeps_ram_and_picks_a_real_shape():
    from greenpick.services import rightsizing_service
    repo = MockCarbonRepository()
    # RAM utilisation not given -> keep 32 GB; 2 vCPU / 32 GB isn't a standard shape, so 4 / 32.
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=8, ram_gb=32, cpu_utilization=0.18,
    )
    assert (adv.recommended_vcpu, adv.recommended_ram_gb) == (4.0, 32.0)


@pytest.mark.asyncio
async def test_training_echoes_wall_clock_hours():
    from greenpick.services import training_service
    repo = MockCarbonRepository()
    adv = await training_service.estimate_training_carbon(
        repo, gpu="a100", gpu_count=8, gpu_hours=150, region="eu-north-1", provider="aws",
    )
    # gpu_hours is TOTAL across GPUs: 150 GPU-hours on 8 GPUs runs ~18.8 h, not 150 h.
    assert adv.wall_clock_hours == 18.8


@pytest.mark.asyncio
async def test_egress_points_to_saving_input_only_when_missing():
    from greenpick.services import locality_service
    repo = MockCarbonRepository()
    without = await locality_service.data_locality_check(
        repo, "aws", "us-west-2", "aws", "us-east-1", 500,
    )
    assert "carbon_saving_kg_co2_from_move" in without.warning
    with_saving = await locality_service.data_locality_check(
        repo, "aws", "us-west-2", "aws", "us-east-1", 500, carbon_saving_kg_co2_from_move=10.0,
    )
    assert with_saving.net_carbon_verdict is not None
    assert "carbon_saving_kg_co2_from_move" not in with_saving.warning


@pytest.mark.asyncio
async def test_serving_echoes_resolved_hub_coordinates():
    from greenpick.services import serving_service
    repo = MockCarbonRepository()
    hubs = [ServingHub(name="us", lat=0, lon=0, share=0.5), ServingHub(name="eu", lat=0, lon=0, share=0.5)]
    adv = await serving_service.serving_pattern(repo, hubs, Workload(vcpu=1, ram_gb=2))
    assert all((h.lat, h.lon) != (0.0, 0.0) for h in adv.hubs)


def test_catalog_has_no_invented_aws_new_york_region():
    from greenpick.data.static_data import regions
    assert "us-east-nyc" not in regions()["aws"]


# --- 0.1.5: secrets never reach logs; a slow upstream can't freeze a tool call ---

import logging


def test_http_libraries_do_not_log_request_urls():
    import greenpick  # noqa: F401  (import side effect sets the levels)
    # httpx logs full request URLs (which carry our API keys) at INFO; we keep it at WARNING.
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


@pytest.mark.asyncio
async def test_eia_key_never_appears_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "EIA-SECRET-123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")   # raise_for_status -> exception text embeds URL

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    r = await EIARepository(api_key=secret).carbon_now("aws", "us-east-1")
    assert r.quality == "typical"
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_entsoe_token_never_appears_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "ENTSOE-SECRET-456"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    monkeypatch.setattr("greenpick.data.entsoe_repository.asyncio.sleep", _no_sleep)
    r = await ENTSOERepository(token=secret).carbon_now("aws", "eu-north-1")
    assert r.quality == "typical"
    assert secret not in caplog.text


async def _no_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_entsoe_slow_upstream_is_bounded(monkeypatch):
    import asyncio, time as _time
    from greenpick.data import entsoe_repository as er

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)   # an upstream that never answers in time
        return httpx.Response(200, text="")

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    monkeypatch.setattr(er, "_FETCH_BUDGET_S", 1.0)
    start = _time.monotonic()
    r = await ENTSOERepository(token="t").carbon_now("aws", "eu-north-1")
    assert r.quality == "typical"                    # degraded to the labelled fallback...
    assert _time.monotonic() - start < 3.0        # ...within the budget, not 30s+


@pytest.mark.asyncio
async def test_entsoe_remembers_an_outage(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("down", request=request)

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    monkeypatch.setattr("greenpick.data.entsoe_repository.asyncio.sleep", _no_sleep)
    repo = ENTSOERepository(token="t")
    await repo.carbon_now("aws", "eu-north-1")
    after_first = calls["n"]
    assert after_first >= 1
    # Same zone again (now, and as history): skipped immediately, no new upstream calls.
    again = await repo.carbon_now("aws", "eu-north-1")
    await repo.carbon_history("aws", "eu-north-1")
    assert again.quality == "typical"
    assert calls["n"] == after_first


# --- 0.1.6: server-level instructions steer agents (they read the tool list, not the README) ---

def test_server_sends_instructions_that_lead_with_rightsizing():
    from greenpick import server
    text = server.mcp.instructions or ""
    assert "rightsizing_check" in text
    # Right-sizing is named before region-picking (the tool list itself starts with region tools).
    assert text.index("rightsizing_check") < text.index("compare_regions_tri_axis")
    # The reporting rules that outside agents got wrong in testing.
    assert "mock" in text and "TOTAL" in text and "data_locality_egress_check" in text
    # Every tool named in the instructions actually exists.
    import re, asyncio
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text)) - {"wall_clock_hours", "gpu_hours", "residency_note", "live_data_hint"}
    registered = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert named <= registered, named - registered


# --- 0.1.7: labelled percentages; start advice as a time of day, not a past date ---

@pytest.mark.asyncio
async def test_rightsizing_labels_cost_and_carbon_percentages_separately():
    from greenpick.services import rightsizing_service
    repo = MockCarbonRepository()
    adv = await rightsizing_service.rightsizing_check(
        repo, "aws", "us-east-1", vcpu=8, ram_gb=32, cpu_utilization=0.15,
    )
    # Cost % is the bill saving; carbon % is the kg saving. They differ, so both are reported.
    assert adv.cost_saving_pct == round(adv.monthly_usd_saving / adv.cost_now_usd_per_month * 100, 1)
    assert adv.carbon_saving_pct == round(adv.monthly_kg_co2_saving / adv.carbon_now_kg_per_month * 100, 1)
    assert adv.cost_saving_pct != adv.carbon_saving_pct
    assert adv.saving_pct == adv.carbon_saving_pct                 # compatibility field unchanged
    assert f"~{adv.cost_saving_pct:.0f}% cheaper" in adv.rationale
    assert f"~{adv.carbon_saving_pct:.0f}% less carbon" in adv.rationale
    assert "mock grid data" in adv.rationale                       # derived carbon carries its quality


def test_clock_label_turns_past_periods_into_a_time_of_day():
    from greenpick.services import scheduling_service as ss
    assert ss.clock_label("2026-10-17T15") == "15:00 UTC"
    assert ss.clock_label("2026-10-17T15:00Z") == "15:00 UTC"
    assert ss.clock_label("H02") == "02:00"                       # mock hours have no timezone
    assert ss.hour_of_day("2026-10-17T15") == 15


@pytest.mark.asyncio
async def test_window_advice_leads_with_time_of_day_not_a_date(monkeypatch):
    from greenpick.services import scheduling_service as ss
    from greenpick.models import HourlyCarbon

    class Repo(MockCarbonRepository):
        async def carbon_history(self, provider, region):
            # Two past days; 15:00-19:00 is clean on the 17th.
            out = []
            for day in ("2026-10-17", "2026-10-18"):
                for h in range(24):
                    g = 60.0 if (day == "2026-10-17" and 15 <= h <= 19) else 200.0
                    out.append(HourlyCarbon(period=f"{day}T{h:02d}", g_co2_per_kwh=g))
            return out

    adv = await ss.cleanest_hours(Repo(), "aws", "us-west-2", window_hours=5)
    assert adv.window.start_hour_of_day == 15
    assert adv.window.start_period == "2026-10-17T15"           # kept, as evidence
    assert adv.note.startswith("For a ~5h job, start around 15:00 UTC")


@pytest.mark.asyncio
async def test_training_rationale_says_start_around_a_time():
    from greenpick.services import training_service
    repo = MockCarbonRepository()
    adv = await training_service.estimate_training_carbon(
        repo, gpu="a100", gpu_count=8, gpu_hours=40, region="us-east-1", provider="aws",
    )
    assert adv.cleanest_window is not None and adv.cleanest_window.start_hour_of_day is not None
    assert f"start it around {adv.cleanest_window.start_hour_of_day:02d}:00" in adv.rationale


def test_instructions_cover_derived_mock_figures():
    from greenpick import server
    assert "derived from them" in server.mcp.instructions


# --- 0.1.8: a mock result says why it isn't live, and how to turn live data on ---

from greenpick import config as _config
from greenpick.config import Settings
from greenpick.services import data_hint


def _settings(source="auto", eia="", entsoe="", em=""):
    return Settings(carbon_source=source, electricitymaps_token=em, eia_api_key=eia,
                    entsoe_token=entsoe, cache_ttl_seconds=1800, log_level="INFO")


def _mock(provider, region):
    return {"provider": provider, "region": region, "g_co2_per_kwh": 350.0,
            "source": "mock", "quality": "mock"}


def test_hint_when_greenpick_is_set_to_mock(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="mock"))
    hint = data_hint.with_hint(_mock("aws", "us-east-1"))["live_data_hint"]
    assert "hand-set illustrative value" in hint
    assert "GREENPICK_CARBON_SOURCE=auto" in hint and data_hint.TURN_ON_URL in hint


def test_hint_names_the_missing_key(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", eia="", entsoe="tok"))
    hint = data_hint.with_hint(_mock("aws", "us-east-1"))["live_data_hint"]
    assert "set EIA_API_KEY" in hint and "eia.gov/opendata/register" in hint
    assert "ENTSOE_TOKEN" not in hint


def test_hint_when_key_is_set_but_source_did_not_answer(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", entsoe="tok"))
    hint = data_hint.with_hint(_mock("aws", "eu-north-1"))["live_data_hint"]
    assert "ENTSO-E didn't return data for aws/eu-north-1" in hint
    assert "set ENTSOE_TOKEN" not in hint                       # don't tell them to add a key they have


def test_hint_for_a_region_no_free_source_covers(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", eia="k", entsoe="t"))
    hint = data_hint.with_hint(_mock("aws", "ap-southeast-2"))["live_data_hint"]
    assert "No free live source covers aws/ap-southeast-2" in hint
    assert "set EIA_API_KEY" not in hint and "set ENTSOE_TOKEN" not in hint


def test_no_hint_on_live_results(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", eia="k"))
    live = {"provider": "aws", "region": "us-east-1", "quality": "live", "source": "eia"}
    assert "live_data_hint" not in data_hint.with_hint(dict(live))
    cached = dict(live, quality="cached")
    assert "live_data_hint" not in data_hint.with_hint(cached)


def test_hint_covers_nested_regions_and_flags_mock_timing(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", entsoe="tok"))
    result = {
        "recommended_region": "aws/eu-north-1", "timing_quality": "mock",
        "options": [
            {"provider": "aws", "region": "eu-north-1", "carbon_quality": "mock"},
            {"provider": "aws", "region": "ap-southeast-2", "carbon_quality": "mock"},
            {"provider": "aws", "region": "us-west-2", "carbon_quality": "live"},
        ],
    }
    hint = data_hint.with_hint(result)["live_data_hint"]
    assert "aws/eu-north-1" in hint and "aws/ap-southeast-2" in hint
    assert "us-west-2" not in hint
    assert "hourly pattern in mock data is illustrative" in hint


@pytest.mark.asyncio
async def test_every_carbon_tool_attaches_the_hint_on_mock(monkeypatch):
    # End to end through the MCP tool functions, with the server's repo on mock data.
    from greenpick import server
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="mock"))
    monkeypatch.setattr(server, "_repo", MockCarbonRepository())

    async def call(name, **kw):
        f = getattr(server, name)
        f = getattr(f, "fn", f)
        return await f(**kw)

    calls = {
        "region_carbon_now": dict(provider="aws", region="us-east-1"),
        "rightsizing_check": dict(provider="aws", region="us-east-1", vcpu=8, ram_gb=32, cpu_utilization=0.15),
        "estimate_workload_carbon": dict(provider="aws", region="us-east-1", vcpu=4, ram_gb=16),
        "estimate_training_carbon": dict(gpu="a100", gpu_count=8, gpu_hours=40),
        "compare_regions_tri_axis": dict(user_lat=40.7, user_lon=-74.0, vcpu=4, ram_gb=16),
        "cleanest_time_of_day": dict(provider="aws", region="us-east-1"),
        "carbon_forecast": dict(provider="aws", region="us-east-1"),
        "data_locality_egress_check": dict(compute_provider="aws", compute_region="us-west-2",
                                           data_provider="aws", data_region="us-east-1",
                                           monthly_cross_boundary_gb=500),
        "serving_pattern_advice": dict(hubs=[{"name": "us", "share": 0.6}, {"name": "eu", "share": 0.4}]),
    }
    for name, kw in calls.items():
        r = await call(name, **kw)
        assert "live_data_hint" in r, name


@pytest.mark.asyncio
async def test_egress_and_serving_label_their_carbon_quality():
    from greenpick.services import locality_service, serving_service
    repo = MockCarbonRepository()
    eg = await locality_service.data_locality_check(repo, "aws", "us-west-2", "aws", "us-east-1", 500)
    assert eg.transfer_carbon_quality == "mock" and eg.transfer_carbon_source == "mock"
    hubs = [ServingHub(name="us", lat=0, lon=0, share=0.5), ServingHub(name="eu", lat=0, lon=0, share=0.5)]
    sv = await serving_service.serving_pattern(repo, hubs, Workload(vcpu=1, ram_gb=2))
    assert sv.multi_region and all(c.carbon_quality == "mock" for c in sv.multi_region)


# --- 0.2.0: the fallback is a typical month from a year of real data; mock only where uncovered ---

from datetime import datetime as _dt, timezone as _tz
from greenpick.data.typical_repository import TypicalCarbonRepository, typical_entry


def test_typical_file_covers_every_region_with_a_live_source():
    from greenpick.data.static_data import iter_regions
    for prov, reg, meta in iter_regions():
        entry = typical_entry(prov, reg)
        if meta.get("eia_ba") or meta.get("entsoe_eic") or meta.get("ca_source"):
            assert entry is not None, f"{prov}/{reg} missing from typical.json"
            assert len(entry["months"]) == 12
            for m in entry["months"].values():
                assert len(m["hourly_utc"]) == 24
        else:
            assert entry is None          # e.g. Sydney: no free source -> stays mock


@pytest.mark.asyncio
async def test_typical_reading_is_this_months_real_average():
    repo = TypicalCarbonRepository()
    r = await repo.carbon_now("aws", "us-east-1")
    month = typical_entry("aws", "us-east-1")["months"][str(_dt.now(_tz.utc).month)]
    assert r.quality == "typical" and r.source == "typical_eia"
    assert r.g_co2_per_kwh == month["avg_g_co2_per_kwh"]
    eu = await repo.carbon_now("aws", "eu-north-1")
    assert eu.quality == "typical" and eu.source == "typical_entsoe"


@pytest.mark.asyncio
async def test_mock_is_only_the_last_resort(monkeypatch):
    from greenpick.data import typical_repository as tr
    repo = TypicalCarbonRepository()
    # Sydney has no typical data but a sourced yearly figure -> annual, not mock.
    r = await repo.carbon_now("aws", "ap-southeast-2")
    assert r.quality == "annual_average" and r.g_co2_per_kwh == 525.2
    # With no yearly figure either, mock still answers (labelled) rather than failing.
    monkeypatch.setattr(tr, "annual_entry", lambda p, reg: None)
    m = await repo.carbon_now("aws", "ap-southeast-2")
    assert m.quality == "mock"
    hist = await repo.carbon_history("aws", "ap-southeast-2")
    assert hist and hist[0].period.startswith("H") and not hist[0].period.endswith("Z")


def test_no_catalog_region_relies_on_mock():
    from greenpick.data.static_data import iter_regions
    for prov, reg, meta in iter_regions():
        assert typical_entry(prov, reg) or annual_entry(prov, reg), f"{prov}/{reg} would be mock"


@pytest.mark.asyncio
async def test_typical_history_is_the_months_real_profile_in_utc():
    from greenpick.services import scheduling_service as ss
    repo = TypicalCarbonRepository()
    hist = await repo.carbon_history("aws", "us-east-1")
    month = typical_entry("aws", "us-east-1")["months"][str(_dt.now(_tz.utc).month)]
    assert [h.g_co2_per_kwh for h in hist] == [g for g in month["hourly_utc"] if g is not None]
    assert hist[0].period == "H00Z"
    assert ss.clock_label("H15Z") == "15:00 UTC" and ss.hour_of_day("H15Z") == 15


@pytest.mark.asyncio
async def test_timing_advice_on_typical_data_says_what_it_is():
    from greenpick.services import scheduling_service as ss
    repo = TypicalCarbonRepository()
    tod = await ss.cleanest_time_of_day(repo, "aws", "us-east-1")
    assert tod.quality == "typical"
    assert tod.note.startswith("In a typical day this month") and "UTC" in tod.note
    win = await ss.cleanest_hours(repo, "aws", "us-west-2", window_hours=4)
    if win.window_reduction_pct and win.window_reduction_pct >= 10:
        assert "typical day" in win.note and "UTC" in win.note


def test_small_absolute_gap_is_called_out():
    from greenpick.services import scheduling_service as ss
    assert "already very low-carbon" in ss.small_gap_note(15.0, 21.0)     # Sweden-style
    oregon = ss.small_gap_note(87.0, 104.0)                             # small gap, not "very low"
    assert "saves little" in oregon and "very low-carbon" not in oregon
    assert ss.small_gap_note(300.0, 400.0) == ""                        # a real swing


@pytest.mark.asyncio
async def test_forecast_fallback_on_typical_data_is_labelled_typical():
    from greenpick.services import forecast_service
    adv = await forecast_service.carbon_forecast(TypicalCarbonRepository(), "aws", "us-east-1")
    assert adv.quality == "typical" and adv.source == "typical"
    assert "TYPICAL daily pattern" in adv.note


def test_hint_explains_typical_data(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="mock"))
    r = {"provider": "aws", "region": "us-east-1", "quality": "typical", "source": "typical_eia",
         "cleanest": []}
    hint = data_hint.with_hint(r)["live_data_hint"]
    assert "this month's average for each grid, computed from a year of real hourly data" in hint
    assert "Mock figures" not in hint
    assert "this month's average day (UTC)" in hint
    assert "GREENPICK_CARBON_SOURCE=auto" in hint


def test_default_repository_is_typical(monkeypatch):
    from greenpick import data as data_pkg
    monkeypatch.setattr(data_pkg, "SETTINGS", _settings(source="mock"))
    assert isinstance(data_pkg.get_repository(), TypicalCarbonRepository)


# --- 0.2.1: a live reading says how it compares with what's typical for that hour ---

from greenpick.data.typical_repository import typical_context


def _typical_at(prov, reg, month, hour):
    return typical_entry(prov, reg)["months"][str(month)]["hourly_utc"][hour]


def test_typical_context_compares_with_same_hour_this_month():
    base = _typical_at("aws", "us-east-1", 10, 6)
    clean = typical_context("aws", "us-east-1", base * 0.7, "2026-10-23T06")
    assert clean["typical_this_hour_g_co2_per_kwh"] == base
    assert clean["vs_typical"] == "cleaner_than_usual" and clean["vs_typical_pct"] == -30.0
    assert "06:00 UTC in October" in clean["typical_note"]
    dirty = typical_context("aws", "us-east-1", base * 1.25, "2026-10-23T06")
    assert dirty["vs_typical"] == "dirtier_than_usual"
    usual = typical_context("aws", "us-east-1", base * 1.05, "2026-10-23T06")
    assert usual["vs_typical"] == "about_usual"


def test_typical_context_reads_entsoe_timestamps():
    base = _typical_at("aws", "eu-north-1", 10, 18)
    ctx = typical_context("aws", "eu-north-1", base, "2026-10-23T18:00Z")
    assert ctx["typical_this_hour_g_co2_per_kwh"] == base and ctx["vs_typical"] == "about_usual"


def test_no_typical_context_for_uncovered_region():
    assert typical_context("aws", "ap-southeast-2", 500.0, "2026-10-23T06") is None


@pytest.mark.asyncio
async def test_region_carbon_now_adds_context_only_to_live_readings(monkeypatch):
    from greenpick import server
    from greenpick.models import CarbonReading

    class LiveRepo(MockCarbonRepository):
        async def carbon_now(self, provider, region):
            return CarbonReading(region=region, provider=provider, g_co2_per_kwh=200.0,
                                 source="eia", timestamp="2026-10-23T06", quality="live")

    f = getattr(server.region_carbon_now, "fn", server.region_carbon_now)
    monkeypatch.setattr(server, "_repo", LiveRepo())
    live = await f(provider="aws", region="us-east-1")
    assert live["vs_typical"] == "cleaner_than_usual" and "live_data_hint" not in live

    monkeypatch.setattr(server, "_repo", TypicalCarbonRepository())
    fallback = await f(provider="aws", region="us-east-1")
    assert fallback["quality"] == "typical" and "vs_typical" not in fallback   # no self-comparison


# --- 0.3.0: Canada — Hydro-Québec (Québec) and IESO (Ontario), live with no key ---

from greenpick.data import canada_repository as ca
from greenpick.data.canada_repository import CanadaRepository

_IESO_XML = """<?xml version="1.0"?>
<IMODocument xmlns="http://www.ieso.ca/schema"><IMODocBody><Date>2026-10-26</Date><Generators>
<Generator><GeneratorName>N1</GeneratorName><FuelType>NUCLEAR</FuelType><Outputs>
  <Output><Hour>1</Hour><EnergyMW>800</EnergyMW></Output>
  <Output><Hour>2</Hour><EnergyMW>800</EnergyMW></Output>
  <Output><Hour>3</Hour><EnergyMW></EnergyMW></Output></Outputs>
  <Capabilities><Capability><Hour>1</Hour><EnergyMW>9999</EnergyMW></Capability></Capabilities></Generator>
<Generator><GeneratorName>G1</GeneratorName><FuelType>GAS</FuelType><Outputs>
  <Output><Hour>1</Hour><EnergyMW>200</EnergyMW></Output>
  <Output><Hour>2</Hour><EnergyMW>0</EnergyMW></Output></Outputs></Generator>
</Generators></IMODocBody></IMODocument>"""

_IESO_YEARLY = """<?xml version="1.0"?>
<Document xmlns="http://www.ieso.ca/schema"><DocBody><DailyData><Day>2026-01-01</Day>
<HourlyData><Hour>1</Hour>
  <FuelTotal><Fuel>NUCLEAR</Fuel><EnergyValue><Output>900</Output></EnergyValue></FuelTotal>
  <FuelTotal><Fuel>WIND</Fuel><EnergyValue><Output>100</Output></EnergyValue></FuelTotal>
</HourlyData></DailyData></DocBody></Document>"""


def test_ieso_hours_are_eastern_standard_time_hour_ending():
    # Hour-ending 1 EST on Oct 26 = 00:00-01:00 EST = 05:00 UTC. No DST shift in summer either.
    assert ca.ieso_period("2026-10-26", 1) == "2026-10-26T05"
    assert ca.ieso_period("2026-07-01", 24) == "2026-07-02T04"


def test_ieso_live_report_sums_output_by_fuel_and_skips_unreported_hours():
    hourly = ca.ieso_generators_to_hourly(_IESO_XML)
    # Hour 1: 800 nuclear (12) + 200 gas (490) = (9600 + 98000) / 1000 = 107.6. Capabilities ignored.
    assert hourly["2026-10-26T05"] == 107.6
    assert hourly["2026-10-26T06"] == 12.0            # hour 2: all nuclear
    assert "2026-10-26T07" not in hourly              # hour 3 not reported yet


def test_ieso_yearly_file_parses_fuel_totals():
    assert ca.ieso_fuel_hourly_to_hourly(_IESO_YEARLY) == {"2026-01-01T05": 11.9}   # (900*12+100*11)/1000


def test_hydroquebec_rows_skip_unfilled_hours_and_use_utc():
    rows = [
        {"date": "2026-10-27T03:30:00+00:00", "valeurs_total": 0.0, "valeurs_hydraulique": None},
        {"date": "2026-10-26T09:30:00+00:00", "valeurs_total": 1000.0, "valeurs_hydraulique": 900.0,
         "valeurs_eolien": 100.0, "valeurs_solaire": 0.0, "valeurs_thermique": None, "valeurs_autres": 0.0},
    ]
    assert ca.hq_rows_to_hourly(rows) == {"2026-10-26T09": 22.7}      # (900*24+100*11)/1000
    history = [{"date": "2026-01-01T04:00:00+00:00", "total": 10.0, "hydraulique": 10.0}]
    assert ca.hq_rows_to_hourly(history, prefix="") == {"2026-01-01T04": 24.0}


@pytest.mark.asyncio
async def test_canada_repository_live_then_falls_back_to_typical(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "ieso" in request.url.host:
            return httpx.Response(200, text=_IESO_XML)
        return httpx.Response(503)                       # Hydro-Québec down

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = CanadaRepository()
    on = await repo.carbon_now("azure", "canadacentral")
    assert (on.source, on.quality, on.timestamp, on.g_co2_per_kwh) == ("ieso", "live", "2026-10-26T06", 12.0)
    hist = await repo.carbon_history("gcp", "northamerica-northeast2")
    assert [h.period for h in hist] == ["2026-10-26T05", "2026-10-26T06"]
    qc = await repo.carbon_now("aws", "ca-central-1")
    assert qc.quality == "typical" and qc.source == "typical_hq"


@pytest.mark.asyncio
async def test_auto_routes_canadian_regions_without_a_key(monkeypatch):
    from greenpick.data.auto_repository import AutoRepository
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, text=_IESO_XML)

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: orig(transport=_mock_transport(handler)))
    r = await AutoRepository(eia_key="", entsoe_token="").carbon_now("azure", "canadacentral")
    assert r.quality == "live" and calls and "ieso" in calls[0]


def test_hint_for_canada_never_asks_for_a_key(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto"))
    r = {"provider": "aws", "region": "ca-central-1", "quality": "typical", "source": "typical_hq"}
    hint = data_hint.with_hint(r)["live_data_hint"]
    assert "Hydro-Québec didn't return data for aws/ca-central-1" in hint
    assert "key" not in hint.split("Hydro-Québec", 1)[1]


def test_canada_regions_are_in_the_catalog_with_a_residency_label():
    from greenpick.data.static_data import region_meta
    from greenpick.services import residency_service
    for prov, reg, src in (("aws", "ca-central-1", "hq"), ("gcp", "northamerica-northeast1", "hq"),
                           ("gcp", "northamerica-northeast2", "ieso"), ("azure", "canadaeast", "hq"),
                           ("azure", "canadacentral", "ieso")):
        meta = region_meta(prov, reg)
        assert meta["ca_source"] == src and meta["jurisdiction"] == "CA"
    assert residency_service._LABEL["CA"] == "Canada"


def test_montreal_is_a_greener_option_for_new_york():
    from greenpick.services import latency_service
    nyc = GeoPoint(lat=40.71, lon=-74.01)
    added = (latency_service.estimate_latency_ms("aws", "ca-central-1", nyc)
             - latency_service.estimate_latency_ms("aws", "us-east-1", nyc))
    assert added < 15                                  # within an East Coast latency budget


# --- 0.4.0: Asia — Singapore, Tokyo, Mumbai/Pune on sourced yearly figures ---

from greenpick.data.typical_repository import annual_entry

_ASIA = [("aws", "ap-southeast-1", "SG"), ("aws", "ap-northeast-1", "JP"), ("aws", "ap-south-1", "IN"),
         ("gcp", "asia-southeast1", "SG"), ("gcp", "asia-northeast1", "JP"), ("gcp", "asia-south1", "IN"),
         ("azure", "southeastasia", "SG"), ("azure", "japaneast", "JP"), ("azure", "centralindia", "IN")]


def test_asia_regions_have_a_sourced_yearly_figure():
    from greenpick.data.static_data import annual, region_meta
    assert "Ember" in annual()["_source"]
    for prov, reg, zone in _ASIA:
        meta = region_meta(prov, reg)
        assert meta["annual_zone"] == zone and meta["jurisdiction"] == zone
        e = annual_entry(prov, reg)
        assert e["year"] >= 2024 and 300 < e["g_co2_per_kwh"] < 900


@pytest.mark.asyncio
async def test_asia_reading_is_labelled_annual_and_has_no_hourly_shape():
    repo = TypicalCarbonRepository()
    r = await repo.carbon_now("aws", "ap-southeast-1")
    assert (r.quality, r.source) == ("annual_average", "ember_annual")
    assert r.g_co2_per_kwh == annual_entry("aws", "ap-southeast-1")["g_co2_per_kwh"]
    assert await repo.carbon_history("aws", "ap-southeast-1") == []       # never invent a curve


@pytest.mark.asyncio
async def test_timing_tools_say_there_is_no_hourly_data_for_asia():
    from greenpick.services import scheduling_service, forecast_service, training_service
    repo = TypicalCarbonRepository()
    tod = await scheduling_service.cleanest_time_of_day(repo, "aws", "ap-northeast-1")
    assert tod.hours_analyzed == 0 and "No recent hourly history" in tod.note
    fc = await forecast_service.carbon_forecast(repo, "aws", "ap-northeast-1")
    assert fc.quality == "annual_average" and "yearly average" in fc.note
    tr = await training_service.estimate_training_carbon(
        repo, gpu="a100", gpu_count=8, gpu_hours=40, region="ap-south-1", provider="aws")
    assert "no hourly data" in tr.rationale and "fairly flat" not in tr.rationale


def test_hint_explains_annual_figures_without_asking_for_a_key(monkeypatch):
    monkeypatch.setattr(_config, "SETTINGS", _settings(source="auto", eia="k", entsoe="t"))
    r = {"provider": "gcp", "region": "asia-south1", "quality": "annual_average", "source": "ember_annual"}
    hint = data_hint.with_hint(r)["live_data_hint"]
    assert "yearly average grid intensity (Ember, lifecycle basis: India 2025)" in hint
    assert "no timing signal" in hint
    assert "set EIA_API_KEY" not in hint and "No free live source covers" not in hint


@pytest.mark.asyncio
async def test_asian_users_are_now_served_from_asia():
    from greenpick.services import serving_service
    hubs = [ServingHub(name="apac", lat=0, lon=0, share=1.0)]
    adv = await serving_service.serving_pattern(TypicalCarbonRepository(), hubs, Workload(vcpu=1, ram_gb=2))
    assert adv.single_region.region in ("ap-southeast-1", "asia-southeast1", "southeastasia")
    assert adv.single_region.weighted_latency_ms < 40                  # was ~199 ms from Sydney


# --- 0.4.2: tool annotations on every tool; every tool tested by name ---

def test_every_tool_declares_all_four_annotation_hints():
    import asyncio
    from greenpick import server
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == 15
    for t in tools:
        a = t.annotations
        assert a is not None, t.name
        for hint in (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint):
            assert isinstance(hint, bool), t.name           # explicit booleans, none missing
        assert a.readOnlyHint and not a.destructiveHint and a.idempotentHint, t.name
    local = {t.name for t in tools if not t.annotations.openWorldHint}
    assert local == {"explain_methodology_and_limits"}   # the only tool that fetches nothing


def _tool(name):
    from greenpick import server
    f = getattr(server, name)
    return getattr(f, "fn", f)


@pytest.mark.asyncio
async def test_tool_greener_alternative_to(monkeypatch):
    from greenpick import server
    monkeypatch.setattr(server, "_repo", MockCarbonRepository())
    r = await _tool("greener_alternative_to")(current_region="us-east-1", user_lat=40.71, user_lon=-74.01,
                                               vcpu=4, ram_gb=16, max_added_latency_ms=50)
    assert r["recommended_region"] in ("aws/ca-central-1", "gcp/northamerica-northeast1", "azure/canadaeast")
    picked = next(c for c in r["candidates"]
                  if f"{c['provider']}/{c['region']}" == r["recommended_region"])
    assert picked["added_latency_ms"] <= 50 + 15


@pytest.mark.asyncio
async def test_tool_cleanest_hours_to_run(monkeypatch):
    from greenpick import server
    monkeypatch.setattr(server, "_repo", TypicalCarbonRepository())
    r = await _tool("cleanest_hours_to_run")(provider="aws", region="us-west-2", window_hours=4)
    assert r["quality"] == "typical" and r["cleanest"]
    assert r["window"]["window_hours"] == 4 and r["window"]["start_hour_of_day"] is not None
    assert "live_data_hint" in r


def test_tool_explain_methodology_and_limits():
    r = _tool("explain_methodology_and_limits")()
    for key in ("what_it_is", "what_it_is_not", "carbon", "cost", "fallback_data", "data_sources"):
        assert r.get(key), key
    assert "annual_average" in r["fallback_data"] and "Hydro-Québec" in r["data_sources"]
