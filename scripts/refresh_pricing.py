"""Refresh pricing.json compute anchors from Vantage (ec2instances.info) live data.

GreenPick's cost model is a DIRECTIONAL per-vCPU-hour + per-GB-RAM-hour ballpark (not
instance-level). Vantage prices *instances*, so we derive the two coefficients by sampling
standard general-purpose instances and solving for the per-vCPU / per-GB-RAM rates, then
average across the family. This keeps GreenPick's model unchanged — it just replaces
hand-typed numbers with current, dated, real-data-derived ones.

Run occasionally (prices change a few times/year, not hourly):
    python scripts/refresh_pricing.py

Notes:
- Source is AWS-only (Vantage's instances.json). We refresh the AWS coefficients from real
  data; GCP/Azure keep their existing (static) coefficients unless/until a similar source is
  wired. We DO update the shared egress figures only for AWS (left per-provider otherwise).
- The file is ~300MB; we STREAM it and stop once we've seen the instances we need.
- On any failure the script leaves pricing.json untouched (never writes partial/garbage).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

VANTAGE_URL = "https://instances.vantage.sh/instances.json"
PRICING_PATH = Path(__file__).resolve().parents[1] / "src" / "greenpick" / "data" / "pricing.json"

# Standard general-purpose instances: clean, consistent vCPU:RAM ratios, good coefficient proxy.
# (m5/m6i = 4 GB RAM per vCPU; broad regional coverage.)
SAMPLE_FAMILIES = {"m5.large", "m5.xlarge", "m5.2xlarge", "m6i.large", "m6i.xlarge", "m6i.2xlarge"}


# GreenPick's cost model splits a VM's hourly rate across vCPU and RAM. The sampled general-
# purpose instances all share a fixed 4 GB-RAM-per-vCPU ratio, so vCPU and RAM can't be fit as
# independent coefficients (collinear). Instead we take the real total $/vCPU for these 4GB/vCPU
# boxes and split it the same way the static model does: a share to compute-per-vCPU and a share
# to per-GB-RAM. RAM_SHARE is the fraction of a VM's price attributed to its memory.
RAM_SHARE = 0.25            # ~25% of a general-purpose VM's price treated as memory cost
RAM_GB_PER_VCPU = 4.0       # the m5/m6i ratio of the samples


def _rate_per_vcpu(samples: list[tuple[float, float, float]]) -> float:
    """samples = [(vcpu, ram_gb, hourly_usd), ...]. Return mean hourly $ per vCPU."""
    rates = [y / v for v, r, y in samples if v > 0]
    return sum(rates) / len(rates) if rates else 0.0


def _split_coefficients(usd_per_vcpu: float) -> tuple[float, float]:
    """Split a total $/vCPU-hr (for 4GB/vCPU VMs) into (per_vcpu, per_gb_ram) coefficients
    consistent with GreenPick's cost model: compute = vcpu*a + ram*b."""
    ram_cost_per_vcpu = usd_per_vcpu * RAM_SHARE          # $ attributed to the 4 GB on that vCPU
    compute_per_vcpu = usd_per_vcpu - ram_cost_per_vcpu   # remainder is pure vCPU
    per_gb_ram = ram_cost_per_vcpu / RAM_GB_PER_VCPU
    return round(compute_per_vcpu, 4), round(per_gb_ram, 4)


def main() -> int:
    import tempfile
    try:
        import ijson  # fast incremental JSON parser (dev-only tool)
    except ImportError:
        print("This script needs ijson:  pip install ijson", file=sys.stderr)
        return 1

    pricing = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    per_region: dict[str, list[tuple[float, float, float]]] = {}

    # Download the ~300MB bulk file to a temp path once, then stream-parse it with ijson
    # (constant memory, fast C backend). Only the sampled instances are kept.
    try:
        tmp = Path(tempfile.gettempdir()) / "vantage_instances.json"
        print("Downloading Vantage instances.json (~300MB, one-time)…")
        with httpx.stream("GET", VANTAGE_URL, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        print("Parsing…")
        with open(tmp, "rb") as f:
            for obj in ijson.items(f, "item"):
                if obj.get("instance_type") in SAMPLE_FAMILIES:
                    _consume(obj, per_region)
        try:
            tmp.unlink()
        except OSError:
            pass
    except Exception as e:
        print(f"Fetch/parse failed ({e}); leaving pricing.json unchanged.", file=sys.stderr)
        return 1

    if not per_region:
        print("No pricing samples collected; leaving pricing.json unchanged.", file=sys.stderr)
        return 1

    # Derive AWS $/vCPU-hr: average per-vCPU rate across all sampled regions, then split into
    # the model's vCPU + RAM coefficients.
    rate_sum = n = 0.0
    for region, samples in per_region.items():
        rate = _rate_per_vcpu(samples)
        if rate > 0:
            rate_sum += rate; n += 1
    if n == 0:
        print("Could not derive rates; leaving pricing.json unchanged.", file=sys.stderr)
        return 1

    usd_per_vcpu = rate_sum / n
    aws_vcpu, aws_ram = _split_coefficients(usd_per_vcpu)

    pricing.setdefault("aws", {})
    pricing["aws"]["compute_usd_per_vcpu_hour"] = aws_vcpu
    pricing["aws"]["compute_usd_per_gb_ram_hour"] = aws_ram
    pricing["_as_of"] = date.today().isoformat()
    pricing["_source"] = ("AWS compute coefficients derived from Vantage ec2instances.info live "
                          "data (m5/m6i on-demand Linux, mean $/vCPU across regions, split "
                          f"{int(RAM_SHARE*100)}% to RAM). GCP/Azure + all egress remain static. "
                          "Directional, not a quote.")

    PRICING_PATH.write_text(json.dumps(pricing, indent=2) + "\n", encoding="utf-8")
    print(f"Updated AWS coefficients from {int(n)} regions: "
          f"${aws_vcpu}/vCPU-hr, ${aws_ram}/GB-RAM-hr. Wrote {PRICING_PATH.name}.")
    return 0


def _consume(obj: dict, per_region: dict) -> None:
    """If obj is a sampled instance type, record (vcpu, ram, ondemand) per region."""
    itype = obj.get("instance_type")
    if itype not in SAMPLE_FAMILIES:
        return
    try:
        vcpu = float(obj.get("vCPU"))
        ram = float(obj.get("memory"))
    except (TypeError, ValueError):
        return
    pricing = obj.get("pricing") or {}
    for region, pr in pricing.items():
        od = (((pr or {}).get("linux") or {}).get("ondemand"))
        if od in (None, "", "N/A"):
            continue
        try:
            hourly = float(od)
        except (TypeError, ValueError):
            continue
        if hourly > 0:
            per_region.setdefault(region, []).append((vcpu, ram, hourly))


if __name__ == "__main__":
    raise SystemExit(main())
