"""Where to check a number: the primary source behind each figure GreenPick reports.

GreenPick's estimates are directional, and its results say so. "Go and verify" is only useful if
it says WHERE, so every result that contains a carbon figure or a dollar figure also gets a short
`verify_at` list: which kind of figure, what it is based on, and the public page to check it against.

Kept deliberately small and stable: top-level pages that publish the data (grid operators, the
cloud providers' own pricing pages), not deep links that move. Additive only: it never changes or
removes an existing field.
"""
from __future__ import annotations

from typing import Any, Iterator

# Carbon: the base source name (after stripping "typical_") -> (what it is, where to check it).
_CARBON = {
    "eia": ("US grid data from EIA-930 (hourly generation by fuel)",
            "https://www.eia.gov/electricity/gridmonitor/"),
    "entsoe": ("EU grid data from the ENTSO-E Transparency Platform (generation by fuel)",
               "https://transparency.entsoe.eu/"),
    "hq": ("Québec grid data from Hydro-Québec open data", "https://donnees.hydroquebec.com/"),
    "ieso": ("Ontario grid data from IESO", "https://www.ieso.ca/en/Power-Data"),
    "ember_annual": ("Yearly national grid intensity from Ember, via Our World in Data",
                     "https://ourworldindata.org/grapher/carbon-intensity-electricity"),
    "electricitymaps": ("Grid data from Electricity Maps", "https://www.electricitymaps.com/"),
    # Credit required by TEPCO's permission. No link: TEPCO asks for notice before anyone links to it.
    "tepco": ("Tokyo-area grid data from Tokyo Electric Power Company Holdings, Inc. "
              "(area supply-and-demand results)", None),
}
_ATTRIBUTION = {
    "tepco": ("Source: Tokyo Electric Power Company Holdings, Inc. Carbon intensity estimated by "
              "GreenPick from TEPCO's published area supply-and-demand data."),
}

# Cost: provider -> (compute price page, data-transfer price page).
_PRICING = {
    "aws": ("https://aws.amazon.com/ec2/pricing/on-demand/",
            "https://aws.amazon.com/ec2/pricing/on-demand/"),
    "gcp": ("https://cloud.google.com/compute/vm-instance-pricing",
            "https://cloud.google.com/vpc/network-pricing"),
    "azure": ("https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/",
              "https://azure.microsoft.com/en-us/pricing/details/bandwidth/"),
}
_PROVIDER_NAME = {"aws": "AWS", "gcp": "Google Cloud", "azure": "Azure"}
_SERVERLESS = {"aws": ("AWS Lambda", "https://aws.amazon.com/lambda/pricing/"),
               "gcp": ("Cloud Run", "https://cloud.google.com/run/pricing"),
               "azure": ("Azure Functions", "https://azure.microsoft.com/en-us/pricing/details/functions/")}

_SOURCE_KEYS = ("source", "carbon_source", "transfer_carbon_source",
                "from_carbon_source", "to_carbon_source")
_PROVIDER_KEYS = ("provider", "compute_provider", "data_provider", "from_provider", "to_provider")
_LOCATION_KEYS = ("recommended_region", "compute_location", "data_location", "from", "to")


def _walk(obj: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def verify_at(result: dict) -> list[dict]:
    """The primary sources behind the carbon and cost figures in a tool result (may be empty)."""
    carbon: set[str] = set()
    providers: set[str] = set()
    has_cost = has_egress = has_serverless = False
    for key, value in _walk(result):
        if key in _SOURCE_KEYS and isinstance(value, str):
            base = value[len("typical_"):] if value.startswith("typical_") else value
            if base in _CARBON:
                carbon.add(base)
        elif key in _PROVIDER_KEYS and value in _PRICING:
            providers.add(value)
        elif key in _LOCATION_KEYS and isinstance(value, str) and "/" in value:
            prov = value.split("/", 1)[0]
            if prov in _PRICING:
                providers.add(prov)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "usd" not in key:
                continue
            if "serverless" in key:
                has_serverless = True
            elif "egress" in key:
                has_egress = True
            elif "cost" in key or "saving" in key:      # compute cost or a saving on it
                has_cost = True

    out: list[dict] = []
    for base in sorted(carbon):
        what, url = _CARBON[base]
        out.append({"figure": "grid carbon intensity", "based_on": what, "url": url})
    for prov in sorted(providers):
        compute_url, transfer_url = _PRICING[prov]
        name = _PROVIDER_NAME[prov]
        if has_cost:
            out.append({"figure": "compute cost", "based_on": f"{name} on-demand list prices (dated)",
                        "url": compute_url})
        if has_serverless:
            product, url = _SERVERLESS[prov]
            out.append({"figure": "serverless cost", "based_on": f"{product} list prices (dated)", "url": url})
        if has_egress:
            out.append({"figure": "data-transfer (egress) cost",
                        "based_on": f"{name} data-transfer prices (dated)", "url": transfer_url})
    return out


def attributions(result: dict) -> list[str]:
    """Credits a data provider requires on every result built on its data (e.g. TEPCO)."""
    found = set()
    for key, value in _walk(result):
        if key in _SOURCE_KEYS and isinstance(value, str):
            base = value[len("typical_"):] if value.startswith("typical_") else value
            if base in _ATTRIBUTION:
                found.add(base)
    return [_ATTRIBUTION[b] for b in sorted(found)]


def with_sources(result: dict) -> dict:
    """Add `verify_at` to a result that contains carbon or cost figures, and `data_attribution`
    where a data provider requires credit; leave other fields unchanged."""
    if isinstance(result, dict) and "error" not in result:
        links = verify_at(result)
        if links:
            result["verify_at"] = links
        credits = attributions(result)
        if credits:
            result["data_attribution"] = credits
    return result
