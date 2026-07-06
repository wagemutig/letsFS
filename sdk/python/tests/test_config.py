"""Deterministic tests for letsFS config resolution — no network required."""

from __future__ import annotations

import os

from letsfs.config import (
    Config,
    DEFAULT_AMADEUS_BASE,
    DEFAULT_NOMINATIM_URL,
    DEFAULT_OVERPASS_URL,
    DEFAULT_USER_AGENT,
)


def test_config_defaults(monkeypatch):
    # Ensure no env leaks in.
    for var in (
        "LETSFS_AMADEUS_KEY", "LETSFS_AMADEUS_SECRET", "LETSFS_AMADEUS_BASE",
        "LETSFS_NOMINATIM_URL", "LETSFS_OVERPASS_URL", "LETSFS_USER_AGENT",
        "LETSFS_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    # Point config file away from any real one.
    monkeypatch.setenv("LETSFS_CONFIG_DIR", "/tmp/__letsfs_no_such_dir__")
    cfg = Config.load()
    assert cfg.amadeus_key == ""
    assert cfg.amadeus_secret == ""
    assert cfg.amadeus_base == DEFAULT_AMADEUS_BASE
    assert cfg.nominatim_url == DEFAULT_NOMINATIM_URL
    assert cfg.overpass_url == DEFAULT_OVERPASS_URL
    assert cfg.user_agent == DEFAULT_USER_AGENT
    assert cfg.timeout == 30
    assert not cfg.amadeus_enabled


def test_config_kwargs_override_env(monkeypatch):
    monkeypatch.setenv("LETSFS_AMADEUS_KEY", "env-key")
    monkeypatch.setenv("LETSFS_CONFIG_DIR", "/tmp/__letsfs_no_such_dir__")
    cfg = Config.load(amadeus_key="kwarg-key")
    assert cfg.amadeus_key == "kwarg-key"  # kwarg wins


def test_config_env_overrides_file(monkeypatch, tmp_path):
    # Write a config file.
    cfg_dir = tmp_path / "letsfs"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text('{"amadeus_key": "file-key"}')
    monkeypatch.setenv("LETSFS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("LETSFS_AMADEUS_KEY", "env-key")
    cfg = Config.load()
    assert cfg.amadeus_key == "env-key"  # env wins over file


def test_config_file_used_when_no_env(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "letsfs"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        '{"amadeus_key": "file-key", "timeout": 99}'
    )
    monkeypatch.setenv("LETSFS_CONFIG_DIR", str(cfg_dir))
    for var in (
        "LETSFS_AMADEUS_KEY", "LETSFS_AMADEUS_SECRET", "LETSFS_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.load()
    assert cfg.amadeus_key == "file-key"
    assert cfg.timeout == 99


def test_config_amadeus_enabled_requires_both(monkeypatch):
    monkeypatch.setenv("LETSFS_CONFIG_DIR", "/tmp/__letsfs_no_such_dir__")
    cfg = Config.load(amadeus_key="k", amadeus_secret="")
    assert not cfg.amadeus_enabled
    cfg = Config.load(amadeus_key="k", amadeus_secret="s")
    assert cfg.amadeus_enabled


def test_config_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("LETSFS_CONFIG_DIR", "/tmp/__letsfs_no_such_dir__")
    cfg = Config.load(
        amadeus_base="https://test.api.amadeus.com/",
        nominatim_url="https://nominatim.openstreetmap.org/",
    )
    assert cfg.amadeus_base == "https://test.api.amadeus.com"
    assert cfg.nominatim_url == "https://nominatim.openstreetmap.org"


def test_config_to_dict_redacts_secrets(monkeypatch):
    monkeypatch.setenv("LETSFS_CONFIG_DIR", "/tmp/__letsfs_no_such_dir__")
    cfg = Config.load(amadeus_key="secret-key", amadeus_secret="secret-secret")
    d = cfg.to_dict()
    assert d["amadeus_key"] == "<set>"
    assert d["amadeus_secret"] == "<set>"
    assert d["amadeus_enabled"] is True
