"""Which regions are greenest ON AVERAGE for a month (or the whole year)?

Answers the "across a whole month, which region is greenest on average?" question from the data
GreenPick already bundles: typical.json (12 months of real hourly EIA / ENTSO-E / Hydro-Québec /
IESO data, averaged per calendar month) and annual.json (a sourced yearly national figure, for
regions with no free hourly data).

Pure and offline: no network, no keys. Because it is built from LAST year's data it describes what
is typical for the time of year, not what the grid is doing today (use region_carbon_now or
compare_regions_tri_axis for that).
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Optional

from ..data.static_data import iter_regions
from ..data.typical_repository import annual_entry, typical_entry

LIMITATIONS = (
    "Typical figures are built from the last 12 months of real hourly grid data, averaged per "
    "calendar month. They describe what is normal for the time of year, not today's grid, and "
    "a given year can differ (wind, hydro, outages). Regions marked annual_average have only a "
    "yearly national figure, so they are not month-specific: compare them with the monthly "
    "figures with care. Carbon only; this ranking ignores cost and latency (use "
    "compare_regions_tri_axis for the three together). Directional, not audited."
)


def _month_name(m: int) -> str:
    return calendar.month_name[m]


def rank_regions(
    month: Optional[int] = None,
    whole_year: bool = False,
    providers: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    top_n: Optional[int] = None,
) -> dict:
    now_month = datetime.now(timezone.utc).month
    m = month or now_month
    if not whole_year and not 1 <= m <= 12:
        return {"error": f"month must be 1-12, got {month}.", "ranking": []}

    rows = []
    for prov, reg, meta in iter_regions():
        if providers and prov not in providers:
            continue
        if regions and reg not in regions:
            continue
        entry = typical_entry(prov, reg)
        if entry and entry.get("months"):
            months = {int(k): v for k, v in entry["months"].items()}
            if whole_year:
                hours = sum(v["hours"] for v in months.values())
                value = sum(v["avg_g_co2_per_kwh"] * v["hours"] for v in months.values()) / hours
            elif m in months:
                value = months[m]["avg_g_co2_per_kwh"]
            else:
                continue
            avgs = {k: v["avg_g_co2_per_kwh"] for k, v in months.items()}
            best, worst = min(avgs, key=avgs.get), max(avgs, key=avgs.get)
            rows.append({
                "provider": prov, "region": reg, "name": meta.get("name"),
                "g_co2_per_kwh": round(value, 1), "quality": "typical",
                "source": entry["source"], "data_from": entry["from"][:7], "data_to": entry["to"][:7],
                "year_low_g_co2_per_kwh": avgs[best], "year_high_g_co2_per_kwh": avgs[worst],
                "cleanest_month": _month_name(best), "dirtiest_month": _month_name(worst),
            })
            continue
        yearly = annual_entry(prov, reg)
        if yearly:
            rows.append({
                "provider": prov, "region": reg, "name": meta.get("name"),
                "g_co2_per_kwh": yearly["g_co2_per_kwh"], "quality": "annual_average",
                "source": "ember_annual", "data_from": str(yearly["year"]), "data_to": str(yearly["year"]),
                "year_low_g_co2_per_kwh": None, "year_high_g_co2_per_kwh": None,
                "cleanest_month": None, "dirtiest_month": None,
            })

    if not rows:
        return {"error": "No regions matched.", "ranking": []}

    rows.sort(key=lambda r: r["g_co2_per_kwh"])
    worst = rows[-1]["g_co2_per_kwh"]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["vs_dirtiest_pct"] = round((r["g_co2_per_kwh"] - worst) / worst * 100, 1) if worst else None
    shown = rows[:top_n] if top_n else rows

    period = "the whole year" if whole_year else _month_name(m)
    best_r, worst_r = rows[0], rows[-1]
    ratio = worst_r["g_co2_per_kwh"] / best_r["g_co2_per_kwh"] if best_r["g_co2_per_kwh"] else None
    spread = f" (~{ratio:.0f}x apart)" if ratio and ratio >= 2 else ""
    rationale = (
        f"On a typical {period if whole_year else period + ' day'}, the greenest of {len(rows)} regions is "
        f"{best_r['provider']}/{best_r['region']} at ~{best_r['g_co2_per_kwh']:.0f} gCO2/kWh and the "
        f"dirtiest is {worst_r['provider']}/{worst_r['region']} at ~{worst_r['g_co2_per_kwh']:.0f}"
        f"{spread}. Built from last year's real data, so it shows what is normal for the time of "
        f"year, not what the grid is doing right now.")
    return {
        "period": period, "regions_ranked": len(rows), "ranking": shown,
        "rationale": rationale, "limitations": LIMITATIONS,
    }
