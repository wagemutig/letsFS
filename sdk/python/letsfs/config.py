"""Configuration for the letsFS SDK.

Reads from environment variables and ``~/.letsfs/config.json``. Constructor
arguments always take precedence over env, which always take precedence over
the config file.

Environment variables
---------------------
- ``LETSFS_AMADEUS_KEY`` — Amadeus API key (optional, enables live pricing)
- ``LETSFS_AMADEUS_SECRET`` — Amadeus API secret (optional)
- ``LETSFS_AMADEUS_BASE`` — Amadeus base URL (default ``https://test.api.amadeus.com``)
- ``LETSFS_OVERPASS_URL`` — Override Overpass API URL
- ``LETSFS_NOMINATIM_URL`` — Override Nominatim base URL
- ``LETSFS_USER_AGENT`` — Override the ``User-Agent`` header (default
  ``letsfs-python/0.1.0``)
- ``LETSFS_TIMEOUT`` — HTTP request timeout in seconds (default ``30``)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Defaults ──────────────────────────────────────────────────────────────

VERSION = "0.1.0"
DEFAULT_USER_AGENT = f"letsfs-python/{VERSION}"

DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_AMADEUS_BASE = "https://test.api.amadeus.com"

DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_NOMINATIM_RATE_MS = 1000  # polite delay between Nominatim calls
DEFAULT_OVERPASS_TIMEOUT_S = 25
DEFAULT_OVERPASS_FETCH_CAP = 200  # cap elements fetched from Overpass per query

CONFIG_DIR_ENV = "LETSFS_CONFIG_DIR"
CONFIG_FILENAME = "config.json"


# ── Config dataclass ──────────────────────────────────────────────────────

@dataclass
class Config:
    """Resolved letsFS configuration."""

    amadeus_key: str = ""
    amadeus_secret: str = ""
    amadeus_base: str = DEFAULT_AMADEUS_BASE
    nominatim_url: str = DEFAULT_NOMINATIM_URL
    overpass_url: str = DEFAULT_OVERPASS_URL
    user_agent: str = DEFAULT_USER_AGENT
    timeout: int = DEFAULT_TIMEOUT
    nominatim_rate_ms: int = DEFAULT_NOMINATIM_RATE_MS
    overpass_timeout_s: int = DEFAULT_OVERPASS_TIMEOUT_S
    overpass_fetch_cap: int = DEFAULT_OVERPASS_FETCH_CAP

    # ── Resolution ───────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        *,
        amadeus_key: Optional[str] = None,
        amadeus_secret: Optional[str] = None,
        amadeus_base: Optional[str] = None,
        nominatim_url: Optional[str] = None,
        overpass_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> "Config":
        """Build a :class:`Config` from kwargs → env → config file → defaults.

        Explicit kwargs win; then environment variables; then
        ``~/.letsfs/config.json``; then hard-coded defaults.
        """
        file_cfg = _read_config_file()

        def pick(kw: Optional[str], env: str, key: str, default: str) -> str:
            if kw is not None:
                return kw
            v = os.environ.get(env)
            if v:
                return v
            fv = file_cfg.get(key)
            if fv:
                return str(fv)
            return default

        def pick_int(kw: Optional[int], env: str, key: str, default: int) -> int:
            if kw is not None:
                return kw
            v = os.environ.get(env)
            if v:
                try:
                    return int(v)
                except ValueError:
                    return default
            fv = file_cfg.get(key)
            if fv is not None:
                try:
                    return int(fv)
                except (TypeError, ValueError):
                    return default
            return default

        return cls(
            amadeus_key=pick(amadeus_key, "LETSFS_AMADEUS_KEY", "amadeus_key", ""),
            amadeus_secret=pick(amadeus_secret, "LETSFS_AMADEUS_SECRET", "amadeus_secret", ""),
            amadeus_base=pick(amadeus_base, "LETSFS_AMADEUS_BASE", "amadeus_base", DEFAULT_AMADEUS_BASE).rstrip("/"),
            nominatim_url=pick(nominatim_url, "LETSFS_NOMINATIM_URL", "nominatim_url", DEFAULT_NOMINATIM_URL).rstrip("/"),
            overpass_url=pick(overpass_url, "LETSFS_OVERPASS_URL", "overpass_url", DEFAULT_OVERPASS_URL),
            user_agent=pick(user_agent, "LETSFS_USER_AGENT", "user_agent", DEFAULT_USER_AGENT),
            timeout=pick_int(timeout, "LETSFS_TIMEOUT", "timeout", DEFAULT_TIMEOUT),
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @property
    def amadeus_enabled(self) -> bool:
        """True when both Amadeus key + secret are present."""
        return bool(self.amadeus_key and self.amadeus_secret)

    def to_dict(self) -> dict:
        return {
            "amadeus_key": "<set>" if self.amadeus_key else "",
            "amadeus_secret": "<set>" if self.amadeus_secret else "",
            "amadeus_base": self.amadeus_base,
            "nominatim_url": self.nominatim_url,
            "overpass_url": self.overpass_url,
            "user_agent": self.user_agent,
            "timeout": self.timeout,
            "nominatim_rate_ms": self.nominatim_rate_ms,
            "overpass_timeout_s": self.overpass_timeout_s,
            "overpass_fetch_cap": self.overpass_fetch_cap,
            "amadeus_enabled": self.amadeus_enabled,
        }


# ── Config file helpers ───────────────────────────────────────────────────

def config_path() -> Path:
    """Path to ``~/.letsfs/config.json`` (or override via ``LETSFS_CONFIG_DIR``)."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override) / CONFIG_FILENAME
    return Path.home() / ".letsfs" / CONFIG_FILENAME


def _read_config_file() -> dict:
    """Read ``~/.letsfs/config.json`` if present; return ``{}`` otherwise."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config_file(cfg: dict) -> Path:
    """Write a dict to ``~/.letsfs/config.json``. Creates the directory."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    return p
