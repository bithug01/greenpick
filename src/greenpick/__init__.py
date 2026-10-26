"""GreenPick — design-time sustainability co-pilot (MCP server).

Greener cloud-region choices with honest carbon + cost + latency tradeoffs,
delivered inside the vibe-coding loop. Directional guidance, not audited accounting.
"""

__version__ = "0.3.0"

# httpx logs every request URL at INFO, and our live sources pass their API key / token as a URL
# query parameter — so at the default log level the secret would land in the MCP client's logs.
# Keep the HTTP libraries at WARNING (no request lines) for every entry point that imports us.
import logging as _logging

for _name in ("httpx", "httpcore"):
    _logging.getLogger(_name).setLevel(_logging.WARNING)
