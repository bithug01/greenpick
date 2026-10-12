"""Runtime configuration, read from environment (see .env.example).

Kept tiny and dependency-light: just os.environ, no settings framework.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Load the project-root .env BEFORE reading settings. The MCP client launches the server with
# its own environment (not a shell that sourced .env) and an unpredictable cwd — so we load the
# .env that lives next to the package DETERMINISTICALLY (by path relative to this file), rather
# than relying on find_dotenv's cwd walk (which can miss it or find the wrong one).
# Precedence: a real environment variable (e.g. set in the MCP server's `env` block) WINS over
# .env, so either mechanism works and explicit env config always takes priority.
try:
    from pathlib import Path
    from dotenv import load_dotenv
    _proj_env = Path(__file__).resolve().parents[2] / ".env"   # src/greenpick/config.py -> project root
    if _proj_env.exists():
        load_dotenv(_proj_env, override=False)   # override=False: don't clobber real env vars
except Exception:
    # python-dotenv missing or unreadable .env -> fall back to raw os.environ (mock defaults).
    pass


@dataclass(frozen=True)
class Settings:
    carbon_source: str          # mock | eia | entsoe | electricitymaps | auto
    electricitymaps_token: str
    eia_api_key: str
    entsoe_token: str
    cache_ttl_seconds: int
    log_level: str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            carbon_source=os.environ.get("GREENPICK_CARBON_SOURCE", "mock").strip().lower(),
            electricitymaps_token=os.environ.get("ELECTRICITYMAPS_TOKEN", "").strip(),
            eia_api_key=os.environ.get("EIA_API_KEY", "").strip(),
            entsoe_token=os.environ.get("ENTSOE_TOKEN", "").strip(),
            cache_ttl_seconds=int(os.environ.get("GREENPICK_CACHE_TTL_SECONDS", "1800")),
            log_level=os.environ.get("GREENPICK_LOG_LEVEL", "INFO").strip().upper(),
        )


SETTINGS = Settings.from_env()
