"""Build data/typical.json: per-region, per-calendar-month typical grid carbon from real data.

When live data isn't available, GreenPick falls back to a typical value. This script makes that
value real: for every catalog region with a free live source, it pulls the last 12 months of hourly
carbon intensity (EIA-930 for US, ENTSO-E A75 for EU), computed exactly the way GreenPick computes
live readings (same parsers, same emission factors), and stores for each calendar month:
  - the average gCO2/kWh, and
  - a 24-value hour-of-day profile (UTC),
plus the source and the date range covered. Regions with no free source (e.g. Sydney) are left out
and keep their hand-set mock value.

Run occasionally (a year of data changes slowly; once or twice a year is plenty):
    python scripts/refresh_typical.py                      # all covered regions, writes the file
    python scripts/refresh_typical.py --regions aws/us-east-1 --dry-run   # test one, print only

Needs EIA_API_KEY / ENTSOE_TOKEN (read from .env or the environment). Keys are never printed.
Fails SAFE: a region that can't be fetched is skipped, and existing entries for it are kept.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from greenpick.config import SETTINGS  # noqa: E402  (also loads .env)
from greenpick.data import canada_repository as canada  # noqa: E402
from greenpick.data._net import describe_error  # noqa: E402
from greenpick.data.entsoe_repository import ENTSOERepository  # noqa: E402
from greenpick.data.static_data import emission_factors, iter_regions  # noqa: E402

TYPICAL_PATH = ROOT / "src" / "greenpick" / "data" / "typical.json"
EIA_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
EIA_PAGE = 5000          # EIA's max rows per request
ENTSOE_CHUNK_DAYS = 7    # keep each A75 request small; ENTSO-E is slow on big ranges
MIN_HOURS_PER_MONTH = 24 * 10   # need ~10 days of data before trusting a month's average


def log(msg: str) -> None:
    print(msg, flush=True)


# --- EIA (US) -----------------------------------------------------------------------------------

async def eia_hourly(client: httpx.AsyncClient, ba: str, start: datetime, end: datetime) -> dict[str, float]:
    """{'YYYY-MM-DDTHH': gCO2/kWh} for a balancing authority, paging through EIA's row limit.
    Same fuel-weighted math as EIARepository.carbon_history."""
    factors = emission_factors()["factors_g_co2_per_kwh"]
    by_hour: dict[str, list[tuple[str, float]]] = defaultdict(list)
    offset = 0
    while True:
        params = {
            "api_key": SETTINGS.eia_api_key, "frequency": "hourly", "data[0]": "value",
            "facets[respondent][]": ba, "start": start.strftime("%Y-%m-%dT%H"),
            "end": end.strftime("%Y-%m-%dT%H"), "sort[0][column]": "period",
            "sort[0][direction]": "asc", "offset": str(offset), "length": str(EIA_PAGE),
        }
        for attempt in range(3):
            try:
                resp = await client.get(EIA_URL, params=params)
                resp.raise_for_status()
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"EIA page at offset {offset} failed: {describe_error(e)}") from None
                await asyncio.sleep(2 * (attempt + 1))
        body = resp.json().get("response", {})
        rows = body.get("data", [])
        for r in rows:
            try:
                mwh = float(r.get("value") or 0)
            except (TypeError, ValueError):
                continue
            by_hour[r.get("period")].append((r.get("fueltype"), mwh))
        total = int(body.get("total") or 0)
        offset += len(rows)
        if not rows or offset >= total:
            break
    out: dict[str, float] = {}
    for period, fuels in by_hour.items():
        tot = sum(m for f, m in fuels if m > 0 and f in factors)
        if tot > 0:
            out[period] = sum(m * factors[f] for f, m in fuels if m > 0 and f in factors) / tot
    return out


# --- ENTSO-E (EU) -------------------------------------------------------------------------------

async def entsoe_hourly(client: httpx.AsyncClient, eic: str, start: datetime, end: datetime) -> dict[str, float]:
    """{'YYYY-MM-DDTHH': gCO2/kWh} for an EU area, in weekly A75 chunks. Reuses
    ENTSOERepository._xml_to_hourly, so the math matches live EU readings."""
    parser = ENTSOERepository(token=SETTINGS.entsoe_token)
    out: dict[str, float] = {}
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=ENTSOE_CHUNK_DAYS), end)
        params = {
            "securityToken": SETTINGS.entsoe_token, "documentType": "A75", "processType": "A16",
            "in_Domain": eic, "periodStart": cur.strftime("%Y%m%d%H%M"),
            "periodEnd": nxt.strftime("%Y%m%d%H%M"),
        }
        for attempt in range(3):
            try:
                resp = await client.get(ENTSOE_URL, params=params)
                if resp.status_code in (401, 403):
                    raise RuntimeError("ENTSO-E rejected the token")
                resp.raise_for_status()
                for h in parser._xml_to_hourly(resp.text):
                    out[h.period] = h.g_co2_per_kwh
                break
            except RuntimeError:
                raise
            except Exception as e:
                if attempt == 2:
                    log(f"    week from {cur:%Y-%m-%d} skipped: {describe_error(e)}")
                else:
                    await asyncio.sleep(3 * (attempt + 1))
        cur = nxt
    return out


# --- Canada (no key needed) -------------------------------------------------------------------

HQ_HISTORY = ("https://donnees.hydroquebec.com/api/explore/v2.1/catalog/datasets/"
              "historique-production-electricite-quebec")
IESO_YEARLY = "https://reports-public.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{year}.xml"


async def hq_hourly(client: httpx.AsyncClient) -> dict[str, float]:
    """Hydro-Québec's history dataset (updated about once a year): the latest 12 months it has."""
    latest = (await client.get(f"{HQ_HISTORY}/records",
                               params={"limit": "1", "order_by": "date desc"})).json()["results"][0]["date"]
    end = datetime.fromisoformat(latest)
    start = end - timedelta(days=365)
    resp = await client.get(f"{HQ_HISTORY}/exports/json", params={
        "where": f"date >= '{start.isoformat()}' and date <= '{end.isoformat()}'",
        "order_by": "date"})
    resp.raise_for_status()
    return canada.hq_rows_to_hourly(resp.json(), prefix="")


async def ieso_hourly(client: httpx.AsyncClient, start: datetime, end: datetime) -> dict[str, float]:
    """IESO's yearly by-fuel files for every year the window touches, trimmed to the window."""
    out: dict[str, float] = {}
    for year in range(start.year, end.year + 1):
        resp = await client.get(IESO_YEARLY.format(year=year))
        resp.raise_for_status()
        out.update(canada.ieso_fuel_hourly_to_hourly(resp.text))
    lo, hi = start.strftime("%Y-%m-%dT%H"), end.strftime("%Y-%m-%dT%H")
    return {p: g for p, g in out.items() if lo <= p <= hi}


# --- Aggregate ----------------------------------------------------------------------------------

def summarise(hourly: dict[str, float]) -> dict:
    """Per calendar month: average, 24-hour UTC profile, hours used. Months with too little data
    are dropped rather than guessed."""
    by_month: dict[int, list[float]] = defaultdict(list)
    by_month_hour: dict[tuple[int, int], list[float]] = defaultdict(list)
    for period, g in hourly.items():
        try:
            dt = datetime.strptime(period[:13], "%Y-%m-%dT%H")
        except ValueError:
            continue
        by_month[dt.month].append(g)
        by_month_hour[(dt.month, dt.hour)].append(g)
    months = {}
    for m in range(1, 13):
        vals = by_month.get(m, [])
        if len(vals) < MIN_HOURS_PER_MONTH:
            continue
        profile = []
        for h in range(24):
            hv = by_month_hour.get((m, h), [])
            profile.append(round(sum(hv) / len(hv), 1) if hv else None)
        months[str(m)] = {"avg_g_co2_per_kwh": round(sum(vals) / len(vals), 1),
                          "hourly_utc": profile, "hours": len(vals)}
    return months


async def build(regions: list[tuple[str, str, dict]]) -> dict:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
    start = end - timedelta(days=365)
    results: dict = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        for prov, reg, meta in regions:
            t = time.monotonic()
            try:
                if meta.get("ca_source") == "hq":
                    source, hourly = "hq", await hq_hourly(client)
                elif meta.get("ca_source") == "ieso":
                    source, hourly = "ieso", await ieso_hourly(client, start, end)
                elif meta.get("eia_ba"):
                    if not SETTINGS.eia_api_key:
                        log(f"  {prov}/{reg}: skipped (no EIA_API_KEY)"); continue
                    source, hourly = "eia", await eia_hourly(client, meta["eia_ba"], start, end)
                else:
                    if not SETTINGS.entsoe_token:
                        log(f"  {prov}/{reg}: skipped (no ENTSOE_TOKEN)"); continue
                    source, hourly = "entsoe", await entsoe_hourly(client, meta["entsoe_eic"], start, end)
            except Exception as e:
                log(f"  {prov}/{reg}: FAILED ({e}) — existing entry kept"); continue
            months = summarise(hourly)
            if not months:
                log(f"  {prov}/{reg}: no usable months — existing entry kept"); continue
            periods = sorted(hourly)
            results.setdefault(prov, {})[reg] = {
                "source": source, "zone": meta.get("zone"),
                "from": periods[0], "to": periods[-1], "months": months,
            }
            log(f"  {prov}/{reg}: {source}, {len(hourly):,} hours, {len(months)}/12 months "
                f"({time.monotonic() - t:.0f}s)")
    return results


def zone_key(meta: dict):
    """The grid a region draws from; regions sharing one are fetched once."""
    return meta.get("eia_ba") or meta.get("entsoe_eic") or meta.get("ca_source")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--regions", nargs="*", help="provider/region list (default: all covered)")
    ap.add_argument("--dry-run", action="store_true", help="print results, don't write the file")
    args = ap.parse_args()

    covered = [(p, r, m) for p, r, m in iter_regions() if zone_key(m)]
    if args.regions:
        wanted = set(args.regions)
        covered = [t for t in covered if f"{t[0]}/{t[1]}" in wanted]
    # Regions sharing a grid zone (e.g. aws/us-west-2 and gcp/us-west1) need fetching once.
    by_zone: dict[str, tuple[str, str, dict]] = {}
    for t in covered:
        by_zone.setdefault(zone_key(t[2]), t)
    log(f"Fetching 12 months for {len(by_zone)} grid zone(s) covering {len(covered)} region(s)...")
    fetched = asyncio.run(build(list(by_zone.values())))

    # Copy each zone's result to every region on that zone.
    zone_result = {}
    for prov, regs in fetched.items():
        for reg, entry in regs.items():
            meta = next(m for p, r, m in covered if p == prov and r == reg)
            zone_result[zone_key(meta)] = entry
    new_regions: dict = {}
    for prov, reg, meta in covered:
        entry = zone_result.get(zone_key(meta))
        if entry:
            new_regions.setdefault(prov, {})[reg] = entry

    if args.dry_run:
        for prov, regs in new_regions.items():
            for reg, e in regs.items():
                log(f"\n{prov}/{reg} ({e['source']}, {e['from']} .. {e['to']})")
                for m, v in sorted(e["months"].items(), key=lambda kv: int(kv[0])):
                    prof = [x for x in v["hourly_utc"] if x is not None]
                    log(f"  month {int(m):2d}: avg {v['avg_g_co2_per_kwh']:6.1f}  "
                        f"hourly range {min(prof):6.1f}-{max(prof):6.1f}  ({v['hours']} h)")
        return

    existing = json.loads(TYPICAL_PATH.read_text(encoding="utf-8")) if TYPICAL_PATH.exists() else {}
    regions_out = existing.get("regions", {})
    for prov, regs in new_regions.items():
        regions_out.setdefault(prov, {}).update(regs)
    doc = {
        "_comment": ("Typical grid carbon per region and calendar month, from 12 months of real "
                     "hourly data (EIA-930 / ENTSO-E A75), using GreenPick's own emission factors. "
                     "Used as the fallback when live data isn't available. hourly_utc is the "
                     "average for each hour of the day (UTC). Generated by scripts/refresh_typical.py."),
        "_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "regions": regions_out,
    }
    # Atomic write: never leave a half-written file in the package.
    with tempfile.NamedTemporaryFile("w", delete=False, dir=TYPICAL_PATH.parent,
                                     suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(doc, tmp, indent=1)
    Path(tmp.name).replace(TYPICAL_PATH)
    log(f"\nWrote {TYPICAL_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
