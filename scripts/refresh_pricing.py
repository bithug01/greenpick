"""Refresh pricing.json compute anchors from Vantage (instances.vantage.sh) live data —
APPLES-TO-APPLES across AWS, Azure, and GCP.

GreenPick's cost model is a DIRECTIONAL per-vCPU-hour + per-GB-RAM-hour ballpark. To compare
clouds fairly, we derive all three the SAME way:
  - same instance CLASS: a standard GENERAL-PURPOSE family with a 4 GB-RAM-per-vCPU ratio
    (AWS m5/m6i, GCP n2-standard, Azure D-series v5) — matched so we're not comparing a
    compute-optimized box on one cloud to a memory box on another;
  - same BASIS: on-demand, Linux, per region;
  - same DERIVATION: mean $/vCPU across regions, split RAM_SHARE to memory;
  - same DATE: all three written with one _as_of.

This yields a CONSISTENT directional comparison (not a certified one — vendors define vCPU/RAM
and discounts differently; true parity is impossible, matched-method is the honest best).

Run occasionally (list prices change a few times/year):
    python scripts/refresh_pricing.py

Fails SAFE: on any error for a cloud, that cloud's coefficients are left unchanged.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import httpx

PRICING_PATH = Path(__file__).resolve().parents[1] / "src" / "greenpick" / "data" / "pricing.json"

# GreenPick splits a VM's hourly rate across vCPU and RAM. The matched families are all 4 GB/vCPU,
# so vCPU and RAM are collinear and can't be fit independently — instead take real $/vCPU and
# split a fixed share to RAM, identically for every cloud.
RAM_SHARE = 0.25            # fraction of a general-purpose VM's price attributed to memory
RAM_GB_PER_VCPU = 4.0       # the matched-family ratio (same on all three clouds)


def _aws_family(it: str) -> bool:
    return it in {"m5.large", "m5.xlarge", "m5.2xlarge", "m6i.large", "m6i.xlarge", "m6i.2xlarge"}


def _gcp_family(it: str) -> bool:
    # n2-standard-* are 4 GB/vCPU general purpose.
    return it.startswith("n2-standard-")


_AZ_RE = re.compile(r"^d\d+[a-z]*v5$")   # d<N>...v5 (standard D v5)
def _azure_family(it: str) -> bool:
    it = it.lower()
    if not _AZ_RE.match(it):
        return False
    # Exclude the 'l' (low-memory, 2 GB/vCPU) variants: d16lsv5, d16ldsv5, d16plsv5, ...
    mid = it[1:-2]  # between leading 'd<digits>' and trailing 'v5' — crude but the 'l' flag lives here
    return "l" not in mid


CLOUDS = {
    "aws":   {"url": "https://instances.vantage.sh/instances.json",      "vkey": "vCPU", "fam": _aws_family},
    "gcp":   {"url": "https://instances.vantage.sh/gcp/instances.json",  "vkey": "vCPU", "fam": _gcp_family},
    "azure": {"url": "https://instances.vantage.sh/azure/instances.json","vkey": "vcpu", "fam": _azure_family},
}


def _collect(url: str, vkey: str, fam) -> dict[str, list[tuple[float, float, float]]]:
    """Return {region: [(vcpu, ram_gb, ondemand_usd), ...]} for matched-family instances."""
    import ijson
    per_region: dict[str, list[tuple[float, float, float]]] = {}
    tmp = Path(tempfile.gettempdir()) / f"vantage_{abs(hash(url))}.json"
    with httpx.stream("GET", url, timeout=300) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    try:
        with open(tmp, "rb") as f:
            for obj in ijson.items(f, "item"):
                it = str(obj.get("instance_type", ""))
                if not fam(it):
                    continue
                try:
                    vcpu = float(obj.get(vkey)); ram = float(obj.get("memory"))
                except (TypeError, ValueError):
                    continue
                for region, pr in (obj.get("pricing") or {}).items():
                    od = (((pr or {}).get("linux") or {}).get("ondemand"))
                    if od in (None, "", "N/A"):
                        continue
                    try:
                        hourly = float(od)
                    except (TypeError, ValueError):
                        continue
                    if vcpu > 0 and hourly > 0:
                        per_region.setdefault(region, []).append((vcpu, ram, hourly))
    finally:
        try: tmp.unlink()
        except OSError: pass
    return per_region


def _coefficients(per_region: dict) -> tuple[float, float] | None:
    """Mean $/vCPU across regions -> (per_vcpu, per_gb_ram) via the fixed RAM split."""
    rates = []
    for samples in per_region.values():
        reg_rates = [y / v for v, r, y in samples if v > 0]
        if reg_rates:
            rates.append(sum(reg_rates) / len(reg_rates))
    if not rates:
        return None
    usd_per_vcpu = sum(rates) / len(rates)
    ram_cost_per_vcpu = usd_per_vcpu * RAM_SHARE
    per_vcpu = round(usd_per_vcpu - ram_cost_per_vcpu, 4)
    per_gb_ram = round(ram_cost_per_vcpu / RAM_GB_PER_VCPU, 4)
    return per_vcpu, per_gb_ram


def main() -> int:
    try:
        import ijson  # noqa: F401  (dev-only tool)
    except ImportError:
        print("This script needs ijson:  pip install ijson", file=sys.stderr)
        return 1

    pricing = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    results: dict[str, tuple[float, float]] = {}

    for cloud, cfg in CLOUDS.items():
        try:
            print(f"[{cloud}] downloading + parsing matched general-purpose family…")
            per_region = _collect(cfg["url"], cfg["vkey"], cfg["fam"])
            coef = _coefficients(per_region)
            if coef is None:
                print(f"[{cloud}] no samples; leaving {cloud} unchanged.", file=sys.stderr)
                continue
            results[cloud] = coef
            print(f"[{cloud}] {len(per_region)} regions -> ${coef[0]}/vCPU-hr, ${coef[1]}/GB-RAM-hr")
        except Exception as e:
            print(f"[{cloud}] failed ({e}); leaving {cloud} unchanged.", file=sys.stderr)

    if not results:
        print("No clouds refreshed; pricing.json unchanged.", file=sys.stderr)
        return 1

    for cloud, (per_vcpu, per_gb_ram) in results.items():
        pricing.setdefault(cloud, {})
        pricing[cloud]["compute_usd_per_vcpu_hour"] = per_vcpu
        pricing[cloud]["compute_usd_per_gb_ram_hour"] = per_gb_ram

    pricing["_as_of"] = date.today().isoformat()
    refreshed = "+".join(sorted(results))
    pricing["_source"] = (
        f"Compute coefficients for [{refreshed}] derived from Vantage live data using ONE matched "
        f"method: general-purpose 4GB/vCPU families (AWS m5/m6i, GCP n2-standard, Azure D-series v5), "
        f"on-demand Linux, mean $/vCPU across regions, {int(RAM_SHARE*100)}% split to RAM. "
        f"Egress remains static. Apples-to-apples DIRECTIONAL comparison, not a quote."
    )

    PRICING_PATH.write_text(json.dumps(pricing, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {PRICING_PATH.name} (refreshed: {refreshed}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
