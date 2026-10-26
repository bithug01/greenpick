"""Tell the user WHY a result isn't live, and how to turn live data on.

A fallback label (`quality: "typical"` or `"mock"`) is honest, but on its own it reads like "this
is all GreenPick does". The server log explains the cause ("No EIA_API_KEY set ..."), but MCP
clients don't show server logs to users. So any result that leans on fallback data gets a
top-level `live_data_hint`, explaining what the fallback is and worded for the actual cause:

- GreenPick is configured for mock data (the default)      -> how to switch on live data
- the region's source needs a key that isn't set            -> which key, where to get it free
- the key is set but the source didn't answer / refused it  -> try later or check the key
- no free live source covers the region                     -> mock is the best available

'typical' is this month's average (and average day) from a year of real data — a realistic norm.
'mock' is a hand-set illustrative value, used only where GreenPick has no real data; its hourly
pattern is synthetic, so timing advice built on it isn't meaningful. The hint says which applies.
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from .. import config
from ..data.static_data import region_meta

TURN_ON_URL = "https://github.com/bithug01/greenpick#turn-on-live-data"
_KEYS = {
    "EIA_API_KEY": "https://www.eia.gov/opendata/register.php",
    "ENTSOE_TOKEN": "https://transparency.entsoe.eu/",
    "ELECTRICITYMAPS_TOKEN": "https://www.electricitymaps.com/",
}
_QUALITY_KEYS = ("quality", "carbon_quality", "timing_quality", "transfer_carbon_quality")
_TIMING_KEYS = ("cleanest", "by_hour_of_day", "cleanest_hours", "cleanest_window", "cleanest_upcoming")


def _location(d: dict) -> Optional[tuple[str, str]]:
    """(provider, region) for a result dict, from provider/region fields or a 'prov/region' string."""
    if isinstance(d.get("provider"), str) and isinstance(d.get("region"), str):
        return d["provider"], d["region"]
    for key in ("recommended_region", "data_location"):
        v = d.get(key)
        if isinstance(v, str) and "/" in v:
            prov, reg = v.split("/", 1)
            return prov, reg
    return None


def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


_FALLBACK = ("typical", "mock")


def _scan(result: dict) -> tuple[dict[str, set[tuple[str, str]]], bool, set[str]]:
    """For each fallback kind ('typical' / 'mock'): the regions whose figures use it; whether any
    such figure had no locatable region; and which kinds fed timing advice."""
    regions: dict[str, set[tuple[str, str]]] = {k: set() for k in _FALLBACK}
    unlocated = False
    timing: set[str] = set()
    for d in _walk(result):
        hits = [(key, d[key]) for key in _QUALITY_KEYS if d.get(key) in _FALLBACK]
        if not hits:
            continue
        loc = _location(d)
        for key, kind in hits:
            if loc:
                regions[kind].add(loc)
            else:
                unlocated = True
            if key == "timing_quality" or any(k in d for k in _TIMING_KEYS):
                timing.add(kind)
    return regions, unlocated, timing


def _reason(provider: str, region: str) -> tuple[str, str]:
    """(reason, detail) for why this region's data is mock under the current settings."""
    s = config.SETTINGS
    meta = region_meta(provider, region) or {}  # type: ignore[arg-type]
    src = s.carbon_source

    def needs(key_name: str, have: str, source_label: str) -> tuple[str, str]:
        return ("no_key", key_name) if not have else ("unavailable", source_label)

    if src == "auto":
        if meta.get("eia_ba"):
            return needs("EIA_API_KEY", s.eia_api_key, "EIA")
        if meta.get("entsoe_eic"):
            return needs("ENTSOE_TOKEN", s.entsoe_token, "ENTSO-E")
        return "uncovered", ""
    if src == "eia":
        return needs("EIA_API_KEY", s.eia_api_key, "EIA") if meta.get("eia_ba") else ("wrong_source", "EIA (US only)")
    if src == "entsoe":
        return (needs("ENTSOE_TOKEN", s.entsoe_token, "ENTSO-E") if meta.get("entsoe_eic")
                else ("wrong_source", "ENTSO-E (EU only)"))
    if src == "electricitymaps":
        return needs("ELECTRICITYMAPS_TOKEN", s.electricitymaps_token, "Electricity Maps")
    return "setting", ""


def _names(locs: list[tuple[str, str]]) -> str:
    return ", ".join(f"{p}/{r}" for p, r in sorted(locs))


def _typical_sentence(locs: set[tuple[str, str]]) -> str:
    from ..data.typical_repository import typical_entry
    spans = sorted({(e["from"][:7], e["to"][:7]) for e in (typical_entry(p, r) for p, r in locs) if e})
    span = f" ({spans[0][0]} to {spans[0][1]})" if len(spans) == 1 else ""
    return ("Typical figures here are this month's average for each grid, computed from a year of "
            f"real hourly data{span} — a realistic norm, not a current reading.")


def build_hint(result: dict) -> Optional[str]:
    by_kind, unlocated, timing = _scan(result)
    all_locs = by_kind["typical"] | by_kind["mock"]
    if not all_locs and not unlocated:
        return None

    parts = []
    if by_kind["typical"]:
        parts.append(_typical_sentence(by_kind["typical"]))
    if by_kind["mock"] or (unlocated and not by_kind["typical"]):
        where = f" for {_names(list(by_kind['mock']))}" if by_kind["mock"] else ""
        parts.append(f"Mock figures{where} are a hand-set illustrative value for the grid, used where "
                     "GreenPick has no real data — not a current reading.")
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for loc in all_locs:
        groups.setdefault(_reason(*loc), []).append(loc)
    if unlocated and not groups:
        groups[_reason("", "")] = []

    for (reason, detail), locs in sorted(groups.items()):
        where = f" for {_names(locs)}" if locs else ""
        if reason == "setting":
            parts.append(
                "GreenPick isn't set up for live data (GREENPICK_CARBON_SOURCE is unset or 'mock'). For "
                "live data, set GREENPICK_CARBON_SOURCE=auto plus a free EIA_API_KEY (US) and/or "
                f"ENTSOE_TOKEN (EU) in the server's environment: {TURN_ON_URL}")
        elif reason == "no_key":
            parts.append(f"For live data{where}, set {detail} (free: {_KEYS[detail]}) in the server's "
                         f"environment: {TURN_ON_URL}")
        elif reason == "unavailable":
            parts.append(f"{detail} didn't return data{where} just now, so GreenPick used its fallback. "
                         "Try again later, or check that the key is valid.")
        elif reason == "wrong_source":
            parts.append(f"GREENPICK_CARBON_SOURCE is set to {detail}, which doesn't cover "
                         f"{_names(locs) or 'this region'}. Use GREENPICK_CARBON_SOURCE=auto to route "
                         "each region to its own live source.")
        elif reason == "uncovered":
            parts.append(f"No free live source covers {_names(locs)} yet, so GreenPick uses its "
                         "fallback there.")
    if "typical" in timing:
        parts.append("Timing advice from typical data reflects this month's average day (UTC), a "
                     "reasonable guide, but today's grid can differ — live data gives the real hours.")
    if "mock" in timing:
        parts.append("The hourly pattern in mock data is illustrative, so timing advice built on it "
                     "(cleanest hours, start windows, % reductions) isn't meaningful.")
    return " ".join(parts)


def with_hint(result: dict) -> dict:
    """Add `live_data_hint` to a tool result that uses fallback data; leave others unchanged."""
    hint = build_hint(result)
    if hint:
        result["live_data_hint"] = hint
    return result
