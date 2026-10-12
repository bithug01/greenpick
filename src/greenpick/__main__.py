"""Entry point: run the GreenPick MCP server over stdio.

    python -m greenpick
"""
from __future__ import annotations

import logging
from .config import SETTINGS
from .server import mcp


def main() -> None:
    logging.basicConfig(level=getattr(logging, SETTINGS.log_level, logging.INFO))
    mcp.run()  # stdio transport by default — what MCP clients expect


if __name__ == "__main__":
    main()
