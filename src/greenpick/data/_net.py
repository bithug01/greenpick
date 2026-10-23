"""Shared networking helpers for the live carbon sources.

Two jobs:
- `describe_error`: a log-safe summary of a failed request. httpx exception messages embed the
  full request URL, and our data sources pass their API key / token as a URL query parameter, so
  logging the exception verbatim would write the secret into the MCP client's log files.
- Shared timeouts, so one slow upstream can't freeze a tool call.
"""
from __future__ import annotations

import httpx

# Per-step limits for a single HTTP request (connect / read / write / pool).
REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
# Hard ceiling for ONE request end-to-end. httpx timeouts are per-step, so a server that trickles
# bytes can stretch a request far past them; asyncio.wait_for enforces a true wall-clock limit.
REQUEST_DEADLINE_S = 15.0


def describe_error(e: BaseException) -> str:
    """Error type plus HTTP status (if any) — never the URL, which carries the credential."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    return f"{type(e).__name__}" + (f" (HTTP {status})" if status else "")
