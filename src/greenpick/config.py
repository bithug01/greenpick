"""Runtime configuration, read from environment (see .env.example).

Kept tiny and dependency-light: just os.environ, no settings framework.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Load a .env file into the environment BEFORE we read any settings. Without this,
# values in .env (carbon source, API token) are never seen — the MCP client launches
# the server with its own environment, not a shell that sourced .env.
try:
    from dotenv import load_dotenv, find_dotenv
    # find_dotenv walks up from CWD; also try the project root relative to this file,
    # so it works no matter where the MCP client starts the process.
    _found = find_dotenv(usecwd=True)
    if _found:
        load_dotenv(_found)
    else:
        from pathlib import Path
        _proj_env = Path(__file__).resolve().parents[2] / ".env"  # src/greenpick/config.py -> project root
        if _proj_env.exists():
            load_dotenv(_proj_env)
except Exception:
    # python-dotenv missing or unreadable .env -> fall back to raw os.environ (mock defaults).
    pass


@dataclass(frozen=True)
class Settings:
    carbon_source: str          # mock | electricitymaps | eia | entsoe
    electricitymaps_token: str
    eia_api_key: str
    cache_ttl_seconds: int
    log_level: str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            carbon_source=os.environ.get("GREENPICK_CARBON_SOURCE", "mock").strip().lower(),
            electricitymaps_token=os.environ.get("ELECTRICITYMAPS_TOKEN", "").strip(),
            eia_api_key=os.environ.get("EIA_API_KEY", "").strip(),
            cache_ttl_seconds=int(os.environ.get("GREENPICK_CACHE_TTL_SECONDS", "1800")),
            log_level=os.environ.get("GREENPICK_LOG_LEVEL", "INFO").strip().upper(),
        )


SETTINGS = Settings.from_env()
