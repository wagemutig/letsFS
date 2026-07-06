"""Deterministic tests for the letsFS CLI — no real HTTP."""

from __future__ import annotations

import json
from typing import Any

import pytest

from letsfs import __version__
from letsfs import cli as cli_mod
from letsfs.client import LetsFS


# ── Helpers ───────────────────────────────────────────────────────────────

def _capture_print(capsys):
    return capsys.readouterr().out


def _mock_ls(monkeypatch, *, search_ret=None, resolve_ret=None, details_ret=None):
    """Patch LetsFS so no real network happens during CLI runs."""
    instances = []

    def fake_init(self, *args, **kwargs):
        # Skip the real Config.load(); use defaults.
        from letsfs.config import Config
        self.config = Config.load()
        self.config.nominatim_rate_ms = 0
        self._amadeus_token = None
        self._last_nominatim_call = 0.0
        instances.append(self)

    def fake_search(self, *args, **kwargs):
        if isinstance(search_ret, Exception):
            raise search_ret
        return search_ret

    def fake_resolve_location(self, query):
        if isinstance(resolve_ret, Exception):
            raise resolve_ret
        return resolve_ret

    def fake_get_hotel_details(self, osm_id, osm_type):
        if isinstance(details_ret, Exception):
            raise details_ret
        return details_ret

    monkeypatch.setattr(LetsFS, "__init__", fake_init)
    monkeypatch.setattr(LetsFS, "search", fake_search)
    monkeypatch.setattr(LetsFS, "resolve_location", fake_resolve_location)
    monkeypatch.setattr(LetsFS, "get_hotel_details", fake_get_hotel_details)
    return instances


def _sample_hotels():
    from letsfs.models import Hotel, HotelSearchResult, LocationResult
    return HotelSearchResult(
        total=2,
        hotels=[
            Hotel(osm_id="1", osm_type="node", name="Grand Hotel", stars="5",
                  address="12 Main St", price=120.0, currency="EUR",
                  phone="+1", website="http://x", city="Bali"),
            Hotel(osm_id="2", osm_type="way", name="Budget Inn", stars="2",
                  address="5 Side Rd"),
        ],
        location="Bali",
        resolved=LocationResult(lat=1.0, lon=2.0,
                                boundingbox=["0", "1", "0", "1"],
                                display_name="Bali, Indonesia"),
        pricing_source="openstreetmap",
        pricing_note="OSM only.",
    )


# ── Tests ─────────────────────────────────────────────────────────────────

def test_cli_version(monkeypatch, capsys):
    # Force argparse path (no typer) for deterministic behaviour.
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["--version"])
    out = _capture_print(capsys)
    assert rc == 0
    assert __version__ in out


def test_cli_no_args_prints_help(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main([])
    out = _capture_print(capsys)
    assert rc == 0
    assert "letsfs" in out.lower()


def test_cli_search_human_readable(monkeypatch, capsys):
    _mock_ls(monkeypatch, search_ret=_sample_hotels())
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["search", "Bali", "--limit", "2"])
    out = _capture_print(capsys)
    assert rc == 0
    assert "Grand Hotel" in out
    assert "Budget Inn" in out
    assert "Bali" in out


def test_cli_search_json(monkeypatch, capsys):
    _mock_ls(monkeypatch, search_ret=_sample_hotels())
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["search", "Bali", "--json"])
    out = _capture_print(capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["location"] == "Bali"
    assert data["total_found"] == 2
    assert data["hotels"][0]["name"] == "Grand Hotel"


def test_cli_search_error_returns_nonzero(monkeypatch, capsys):
    from letsfs.client import LetsFSError
    _mock_ls(monkeypatch, search_ret=LetsFSError("boom"))
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["search", "Nowhere"])
    out = _capture_print(capsys)
    assert rc == 1
    assert "boom" in out


def test_cli_location_json(monkeypatch, capsys):
    from letsfs.models import LocationResult
    loc = LocationResult(
        lat=48.85, lon=2.35,
        boundingbox=["48.81", "48.90", "2.22", "2.47"],
        display_name="Paris, France", type="city",
    )
    _mock_ls(monkeypatch, resolve_ret=loc)
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["location", "Paris", "--json"])
    out = _capture_print(capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["display_name"] == "Paris, France"
    assert data["overpass_bbox"] == "48.81,2.22,48.90,2.47"


def test_cli_hotel_json(monkeypatch, capsys):
    from letsfs.models import HotelDetails
    details = HotelDetails(
        osm_id="42", osm_type="way", name="Detail Hotel",
        stars="3", address="5 Rd", phone="555", website="http://x",
        lat=1.0, lon=2.0,
        tags={"name": "Detail Hotel", "internet_access": "wlan"},
    )
    _mock_ls(monkeypatch, details_ret=details)
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["hotel", "42", "way", "--json"])
    out = _capture_print(capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["osm_id"] == "42"
    assert data["tags"]["internet_access"] == "wlan"


def test_cli_config_json(monkeypatch, capsys):
    _mock_ls(monkeypatch)
    monkeypatch.setattr(cli_mod, "_try_typer_main", lambda argv: None)
    rc = cli_mod.main(["config", "--json"])
    out = _capture_print(capsys)
    assert rc == 0
    data = json.loads(out)
    assert "amadeus_enabled" in data
    assert "overpass_url" in data
