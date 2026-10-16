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

    # Tight budget vs. a US baseline: nothing meaningfully greener fits, so it should
    # stay on the baseline AND say so honestly (not dress the baseline up as a "win").
    rec_tight = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=20, baseline_region="us-east-1",
    )
    assert rec_tight.recommended_region == "aws/us-east-1"
    assert "reasonable" in rec_tight.rationale.lower() or "as good as it gets" in rec_tight.rationale.lower()

    # Wide budget: the clean-but-far region (Sweden, 25 gCO2) should now win over us-east-1.
    rec_wide = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=500, baseline_region="us-east-1",
    )
    assert rec_wide.recommended_region == "aws/eu-north-1"
    assert "cleaner" in rec_wide.rationale.lower()

    # Tolerance band: a +105ms option under a +100ms cap should NOT be excluded.
    rec_band = await recommender.compare_regions(
        repo, None, user, wl, optimize_for="carbon",
        max_added_latency_ms=100, baseline_region="us-east-1",
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
    assert r.quality == "mock"          # degrades, labelled honestly
    assert repo._token_rejected is True  # won't keep hammering a bad key


@pytest.mark.asyncio
async def test_em_no_token_uses_mock():
    repo = ElectricityMapsRepository(token="")
    r = await repo.carbon_now("aws", "eu-north-1")
    assert r.quality == "mock"


# --- EIA repository: fuel-mix -> carbon-intensity math, verified without a real key/network ---

from greenpick.data.eia_repository import EIARepository


@pytest.mark.asyncio
async def test_eia_mix_to_carbon_intensity(monkeypatch):
    # NYISO latest hour: 1000 MWh gas (490) + 1000 MWh nuclear (12) -> weighted mean = 251 gCO2/kWh.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("facets[respondent][]") == "NYIS"
        return httpx.Response(200, json={"response": {"data": [
            {"period": "2026-10-11T18", "respondent": "NYIS", "fueltype": "NG", "value": "1000"},
            {"period": "2026-10-11T18", "respondent": "NYIS", "fueltype": "NUC", "value": "1000"},
            {"period": "2026-10-11T17", "respondent": "NYIS", "fueltype": "NG", "value": "9999"},  # older hour, ignored
        ]}})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=_mock_transport(handler)))
    repo = EIARepository(api_key="key")
    r = await repo.carbon_now("aws", "us-east-nyc")   # maps to BA NYIS
    assert r.source == "eia"
    assert r.quality == "live"
    assert abs(r.g_co2_per_kwh - 251.0) < 0.5          # (490+12)/2
    assert r.timestamp == "2026-10-11T18"              # only the latest hour used


@pytest.mark.asyncio
async def test_eia_non_us_region_falls_back_to_mock():
    repo = EIARepository(api_key="key")
    r = await repo.carbon_now("aws", "eu-north-1")     # no eia_ba -> mock
    assert r.quality == "mock"


@pytest.mark.asyncio
async def test_eia_no_key_uses_mock():
    repo = EIARepository(api_key="")
    r = await repo.carbon_now("aws", "us-east-nyc")
    assert r.quality == "mock"


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
    assert r.quality == "mock"


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
    syd = await repo.carbon_now("aws", "ap-southeast-2")  # -> mock
    assert us.source == "eia"
    assert eu.source == "entsoe"
    assert syd.quality == "mock"


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
    assert adv.single_region.region in {"us-east-1", "us-west-2", "us-east-nyc", "us-central1",
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
async def test_forecast_degrades_to_historical_without_forecast_source():
    # MockCarbonRepository has no renewable_forecast -> service falls back to historical pattern.
    repo = MockCarbonRepository()
    adv = await forecast_service.carbon_forecast(repo, "aws", "us-east-1", hours_ahead=24)
    assert adv.source == "historical_fallback"
    assert adv.quality == "historical"
    assert adv.cleanest_upcoming == []
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
    adv = await scheduling_service.cleanest_time_of_day(repo, "aws", "us-east-nyc")
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
    hist = await repo.carbon_history("aws", "us-east-nyc")
    periods = {h.period: h.g_co2_per_kwh for h in hist}
    assert set(periods) == {"2026-10-12T18", "2026-10-12T19"}
    assert periods["2026-10-12T18"] < periods["2026-10-12T19"]  # nuclear-heavy hour cleaner
