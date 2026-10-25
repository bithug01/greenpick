"""Serving-pattern advice: should I serve my users from ONE region or SEVERAL?

A design-time question for a user-facing platform: given where your users are (rough geographic
shares are fine), is it better to serve everyone from a single region, or run multiple regions
closer to each hub? GreenPick scores both on traffic-weighted latency and grid carbon, then
composes the caveats that make multi-region non-free: cross-region DATA-SYNC egress (keeping shared
state consistent across regions) and cross-JURISDICTION residency (a hub served from another
jurisdiction).

Firmly in GreenPick's lane: design-time, directional, stateless, reuses carbon + latency + egress +
residency. It is NOT a runtime meter — it never measures a running app; it advises before you build.
Input (user geography) is soft and often unknown precisely at design time, so rough % shares are
accepted and everything is labelled directional.
"""
from __future__ import annotations

from typing import Optional

from ..models import (
    Workload, GeoPoint, Provider, ServingHub, ServingSinglePlan,
    ServingPerHubChoice, ServingPatternAdvice,
)
from ..data.repository import CarbonRepository
from ..data.static_data import iter_regions, region_meta
from . import carbon_service, latency_service, residency_service

# Representative coordinates for common named hubs, so callers can say "eu"/"us"/"apac" without
# supplying lat/lon. Rough centroids of where users typically are, not of the regions.
_HUB_COORDS = {
    "us": (39.0, -98.0), "us-east": (38.9, -77.0), "us-west": (37.8, -122.3),
    "eu": (50.1, 8.7), "eu-west": (53.3, -6.3), "eu-north": (59.3, 18.1),
    "uk": (51.5, -0.1), "apac": (1.35, 103.8), "au": (-33.9, 151.2),
    "india": (19.1, 72.9), "japan": (35.7, 139.7), "sa": (-23.5, -46.6),
}

LIMITATIONS = (
    "Directional, design-time guidance — NOT a runtime measurement of your app. User geography is "
    "whatever you supply (rough % shares are fine); results are only as good as that estimate. "
    "Multi-region adds operational complexity, data-sync egress, and possible residency constraints "
    "that GreenPick flags but does not fully cost. Carbon/latency are directional (see "
    "explain_methodology_and_limits)."
)


def resolve_hub(h: ServingHub) -> GeoPoint:
    """A hub may give explicit lat/lon, or rely on a known name -> representative coords."""
    key = h.name.strip().lower()
    if key in _HUB_COORDS and (h.lat == 0 and h.lon == 0):
        lat, lon = _HUB_COORDS[key]
        return GeoPoint(lat=lat, lon=lon)
    return GeoPoint(lat=h.lat, lon=h.lon)


async def _carbon(repo: CarbonRepository, provider: str, region: str):
    return await carbon_service.carbon_now(repo, provider, region)  # type: ignore[arg-type]


async def serving_pattern(
    repo: CarbonRepository,
    hubs: list[ServingHub],
    workload: Workload,
    providers: Optional[list[Provider]] = None,
) -> ServingPatternAdvice:
    if not hubs:
        return ServingPatternAdvice(hubs=[], rationale="No user hubs supplied — give at least one "
                                    "(name + rough share) so I can advise on where to serve from.",
                                    limitations=LIMITATIONS)

    # Normalise shares so they sum to 1 (callers often give rough buckets like 40/40/20).
    total_share = sum(h.share for h in hubs) or 1.0
    weights = [h.share / total_share for h in hubs]
    points = [resolve_hub(h) for h in hubs]

    wanted = set(providers) if providers else {"aws", "gcp", "azure"}
    catalog = [(p, r) for p, r, _m in iter_regions() if p in wanted]

    # Carbon per candidate region (one fetch each). Latency is pure geometry, no fetch.
    carbon_cache: dict[tuple[str, str], object] = {}
    import asyncio
    readings = await asyncio.gather(*(_carbon(repo, p, r) for p, r in catalog))
    for (p, r), reading in zip(catalog, readings):
        carbon_cache[(p, r)] = reading

    def latency(p: str, r: str, pt: GeoPoint) -> Optional[float]:
        return latency_service.estimate_latency_ms(p, r, pt)  # type: ignore[arg-type]

    # --- Single-region-for-all: pick the region minimising traffic-weighted latency ---
    best_single = None
    for (p, r) in catalog:
        lats = [latency(p, r, pt) for pt in points]
        if any(l is None for l in lats):
            continue
        wlat = sum(w * l for w, l in zip(weights, lats))  # type: ignore[arg-type]
        if best_single is None or wlat < best_single[0]:
            best_single = (wlat, p, r)

    single_plan = None
    if best_single is not None:
        wlat, p, r = best_single
        reading = carbon_cache[(p, r)]
        single_plan = ServingSinglePlan(
            provider=p, region=r, weighted_latency_ms=round(wlat, 1),  # type: ignore[arg-type]
            carbon_g_co2_per_kwh=reading.g_co2_per_kwh, carbon_source=reading.source,  # type: ignore[attr-defined]
            carbon_quality=reading.quality,  # type: ignore[attr-defined]
        )

    # --- Multi-region: for each hub, the region that best balances latency + carbon near it ---
    per_hub: list[ServingPerHubChoice] = []
    for h, pt, w in zip(hubs, points, weights):
        scored = []
        for (p, r) in catalog:
            l = latency(p, r, pt)
            if l is None:
                continue
            reading = carbon_cache[(p, r)]
            # Rank each hub's region by latency first (serving locality is the point of going
            # multi-region), using carbon as the tiebreaker among nearby options (+/-30ms).
            scored.append((l, reading.g_co2_per_kwh, p, r))  # type: ignore[attr-defined]
        if not scored:
            continue
        scored.sort(key=lambda t: t[0])
        near_min = scored[0][0] + 30.0
        nearby = [s for s in scored if s[0] <= near_min]
        nearby.sort(key=lambda t: t[1])   # greenest among the near-latency options
        l, g, p, r = nearby[0]
        reading = carbon_cache[(p, r)]
        per_hub.append(ServingPerHubChoice(
            hub=h.name, provider=p, region=r, latency_ms=round(l, 1),
            carbon_g_co2_per_kwh=g,
            carbon_source=reading.source, carbon_quality=reading.quality,  # type: ignore[attr-defined]
        ))

    multi_wlat = None
    multi_blended = None
    if len(per_hub) == len(hubs):
        multi_wlat = round(sum(w * c.latency_ms for w, c in zip(weights, per_hub)), 1)
        multi_blended = round(sum(w * c.carbon_g_co2_per_kwh for w, c in zip(weights, per_hub)), 1)

    # --- Caveats that make multi-region non-free ---
    data_sync_note = None
    residency_note = None
    distinct_regions = {(c.provider, c.region) for c in per_hub}
    if len(distinct_regions) > 1:
        data_sync_note = (
            "Multi-region means shared state (DBs, sessions, caches) must sync ACROSS regions — "
            "that cross-region traffic is billed egress and adds its own transfer carbon. Model it "
            "with data_locality_egress_check before committing; it can erase the latency/carbon win "
            "for write-heavy or chatty-shared-state apps.")
        # Residency: does any hub get served from a different jurisdiction than the hub sits in?
        for h, pt, c in zip(hubs, points, per_hub):
            hub_jur = _nearest_jurisdiction(pt)
            serve_jur = residency_service.jurisdiction_of(c.provider, c.region)
            if hub_jur and serve_jur and hub_jur != serve_jur:
                residency_note = (
                    f"RESIDENCY: at least one hub ('{h.name}') would be served from a region in a "
                    f"different jurisdiction ({serve_jur}) than the users appear to sit in ({hub_jur}). "
                    f"If user data is regulated, this may matter. " + residency_service.DISCLAIMER)
                break

    # --- Decide + explain ---
    recommended, rationale = _decide(single_plan, per_hub, multi_wlat, multi_blended,
                                     len(distinct_regions))

    # Echo hubs with the coordinates actually used (named hubs like "eu" resolve to representative
    # coords), so the output never shows a misleading 0,0 for a hub that was resolved by name.
    resolved_hubs = [ServingHub(name=h.name, lat=pt.lat, lon=pt.lon, share=h.share)
                     for h, pt in zip(hubs, points)]

    return ServingPatternAdvice(
        hubs=resolved_hubs, single_region=single_plan, multi_region=per_hub,
        multi_region_weighted_latency_ms=multi_wlat,
        multi_region_blended_carbon_g_co2_per_kwh=multi_blended,
        recommended_pattern=recommended, data_sync_egress_note=data_sync_note,
        residency_note=residency_note, rationale=rationale, limitations=LIMITATIONS,
    )


def _nearest_jurisdiction(pt: GeoPoint) -> Optional[str]:
    """Infer a hub's jurisdiction from the nearest catalogued region's tag (directional)."""
    best = None
    for p, r, meta in iter_regions():
        if "lat" not in meta or "jurisdiction" not in meta:
            continue
        d = (meta["lat"] - pt.lat) ** 2 + (meta["lon"] - pt.lon) ** 2
        if best is None or d < best[0]:
            best = (d, meta["jurisdiction"])
    return best[1] if best else None


def _decide(single, per_hub, multi_wlat, multi_blended, n_distinct):
    """Recommend single vs multi. Single wins unless multi-region materially cuts weighted latency
    (users are genuinely spread), since multi-region's complexity/egress is a real cost."""
    if single is None or not per_hub or multi_wlat is None:
        if single is not None:
            return "single_region", (f"Serve all users from {single.provider}/{single.region} "
                                     f"(~{single.weighted_latency_ms:.0f}ms weighted latency).")
        return "single_region", "Not enough data to compare serving patterns."

    lat_saving = single.weighted_latency_ms - multi_wlat
    if n_distinct > 1 and lat_saving >= 40:
        return "multi_region", (
            f"Your users are spread enough that multi-region helps: serving each hub locally cuts "
            f"weighted latency from ~{single.weighted_latency_ms:.0f}ms (single region) to "
            f"~{multi_wlat:.0f}ms, and blends to ~{multi_blended:.0f} gCO2/kWh. Weigh that against "
            f"the data-sync egress and complexity below before committing.")
    return "single_region", (
        f"A single region ({single.provider}/{single.region}, ~{single.weighted_latency_ms:.0f}ms "
        f"weighted) is the better call: multi-region would only save ~{max(0, lat_saving):.0f}ms, "
        f"which rarely justifies the added data-sync egress and operational complexity.")
