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
