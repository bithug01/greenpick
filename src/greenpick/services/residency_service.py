"""Data-residency AWARENESS — a geographic flag, NEVER a compliance verdict.

GreenPick's recommendations move compute between regions. If a move crosses a data-residency
boundary (most importantly, leaving the EEA), a builder handling regulated or personal data needs
to KNOW — but GreenPick is not qualified to rule on legality, and the legal landscape (adequacy
decisions, frameworks) shifts constantly. So we encode only the STABLE geographic fact — which
jurisdiction a region sits in — and raise a neutral heads-up when a move crosses one, with a hard
disclaimer pointing the user to their own data governance.

What this is:    "this move leaves the EEA — residency rules MAY apply; check your governance."
What this isNOT: "this move is / isn't GDPR-compliant." We never say that.
"""
from __future__ import annotations

from typing import Optional

from ..data.static_data import region_meta

# Human labels for the stable jurisdiction tags in regions.json.
_LABEL = {
    "EEA": "the EEA (EU + Norway/Iceland/Liechtenstein)",
    "US": "the United States",
    "AU": "Australia",
    "CA": "Canada",
    "SG": "Singapore",
    "JP": "Japan",
    "IN": "India",
}

DISCLAIMER = ("GreenPick does NOT assess legal compliance - this is a geographic heads-up only. "
              "Confirm against your own data-residency / data-governance requirements.")


def jurisdiction_of(provider: str, region: str) -> Optional[str]:
    meta = region_meta(provider, region) or {}
    return meta.get("jurisdiction")


def residency_flag(from_provider: str, from_region: str,
                   to_provider: str, to_region: str) -> Optional[str]:
    """Return a neutral residency heads-up if moving from one region to another crosses a
    jurisdiction boundary, else None. States only geography + the category of concern + the
    disclaimer. Leaving the EEA is called out specifically (the GDPR transfer trigger)."""
    j_from = jurisdiction_of(from_provider, from_region)
    j_to = jurisdiction_of(to_provider, to_region)
    if not j_from or not j_to or j_from == j_to:
        return None   # same jurisdiction (or unknown) -> no residency crossing to flag

    to_label = _LABEL.get(j_to, j_to)
    from_label = _LABEL.get(j_from, j_from)
    if j_from == "EEA":
        # The high-stakes direction: data leaving the EEA.
        return (f"RESIDENCY: this move takes compute from {from_label} to {to_label} - i.e. OUT of "
                f"the EEA. If the workload handles personal or regulated data, GDPR transfer rules "
                f"may constrain or prohibit this. {DISCLAIMER}")
    return (f"RESIDENCY: this move crosses jurisdictions ({from_label} → {to_label}). If the workload "
            f"handles regulated or personal data, residency rules may apply. {DISCLAIMER}")
