"""Runtime configuration, read from environment (see .env.example).

Kept tiny and dependency-light: just os.environ, no settings framework.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Load the project-root .env BEFORE reading settings, with NO third-party dependency.
# Why not python-dotenv: the MCP client may launch the server with an interpreter where the
# ambiguous `dotenv` import resolves to the wrong package (collision between python-dotenv and
# the unrelated `dotenv` pkg), silently skipping the load -> everything defaults to mock. A .env
# is just KEY=value lines, so we parse it ourselves, deterministically by path. A real environment
# variable (e.g. set in the MCP server's `env` block) still WINS — we don't overwrite os.environ.
def _load_project_dotenv() -> None:
    from pathlib import Path
    env_path = Path(__file__).resolve().parents[2] / ".env"   # src/greenpick/config.py -> project root
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:   # real env wins; don't clobber
            os.environ[key] = val


_load_project_dotenv()


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
