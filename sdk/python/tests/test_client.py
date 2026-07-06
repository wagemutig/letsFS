"""Deterministic tests for letsFS client — network is mocked, no real calls.

The ``LetsFS`` client's HTTP layer goes through three private methods:

- ``_http_get_json`` (Nominatim, Amadeus GET)
- ``_http_post_json`` (Overpass, Amadeus OAuth)
- ``_do_request`` (the underlying urllib call)

We monkeypatch ``_do_request`` to return canned JSON for each test, so the
end-to-end pipeline (geocode → overpass → shape → optional Amadeus) is
exercised without hitting the network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from letsfs import LetsFS, LetsFSError
from letsfs.config import Config
from letsfs.models import AmadeusOffer, Hotel, HotelDetails, LocationResult


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ls() -> LetsFS:
    """A LetsFS client with no Amadeus credentials and a 0-rate delay."""
    cfg = Config.load()
    cfg.nominatim_rate_ms = 0  # no sleeps in tests
    return LetsFS(config=cfg)


@pytest.fixture
def ls_amad() -> LetsFS:
    """A LetsFS client with Amadeus credentials and a 0-rate delay."""
    cfg = Config.load(amadeus_key="k", amadeus_secret="s")
    cfg.nominatim_rate_ms = 0
    return LetsFS(config=cfg)


# Sample canned responses matching real API shapes.

NOMINATIM_PARIS = [
    {
        "lat": "48.8566",
        "lon": "2.3522",
        "boundingbox": ["48.8156", "48.9016", "2.2241", "2.4699"],
        "display_name": "Paris, Île-de-France, France",
        "type": "city",
    }
]

OVERPASS_PARIS = {
    "elements": [
        {
            "type": "node", "id": 100, "lat": 48.85, "lon": 2.35,
            "tags": {"name": "Hotel Paris", "stars": "4",
                     "addr:housenumber": "1", "addr:street": "Rue"},
        },
        {
            "type": "way", "id": 200, "center": {"lat": 48.86, "lon": 2.36},
            "tags": {"name": "Grand Way Hotel", "stars": "5"},
        },
        {
            "type": "node", "id": 300, "lat": 0, "lon": 0,
            "tags": {"tourism": "hotel"},  # no name — should be filtered out
        },
    ]
}


class MockResponse:
    """A minimal stand-in for urllib's response object."""

    def __init__(self, payload: Any):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _set_http(ls: LetsFS, *, get=None, post=None):
    """Install canned HTTP handlers on a LetsFS instance.

    Each of ``get``/``post`` may be a single payload (returned for every call)
    or a list of payloads (consumed in order).
    """
    state = {"get_idx": 0, "post_idx": 0}

    def fake_do_request(req, url):
        method = req.get_method().upper()
        if method == "GET" and get is not None:
            payload = get
            if isinstance(get, list):
                payload = get[state["get_idx"]]
                state["get_idx"] += 1
            return payload
        if method == "POST" and post is not None:
            payload = post
            if isinstance(post, list):
                payload = post[state["post_idx"]]
                state["post_idx"] += 1
            return payload
        raise AssertionError(f"Unexpected HTTP call: {method} {url}")

    ls._do_request = fake_do_request  # type: ignore[assignment]


# ── resolve_location ──────────────────────────────────────────────────────

def test_resolve_location_success(ls):
    _set_http(ls, get=NOMINATIM_PARIS)
    loc = ls.resolve_location("Paris")
    assert isinstance(loc, LocationResult)
    assert loc.lat == 48.8566
    assert loc.display_name.startswith("Paris")
    assert loc.overpass_bbox == "48.8156,2.2241,48.9016,2.4699"


def test_resolve_location_empty_query_raises(ls):
    with pytest.raises(LetsFSError, match="query is required"):
        ls.resolve_location("")


def test_resolve_location_no_match_raises(ls):
    _set_http(ls, get=[])
    with pytest.raises(LetsFSError, match="No geocoding result"):
        ls.resolve_location("Nowhere")


# ── search ────────────────────────────────────────────────────────────────

def test_search_returns_hotels_from_osm(ls):
    # Nominatim (GET) then Overpass (POST).
    _set_http(ls, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    res = ls.search("Paris", limit=20)
    assert res.total == 2  # unnamed hotel filtered out
    assert res.returned == 2
    assert res.location == "Paris"
    assert res.pricing_source == "openstreetmap"
    assert res.amadeus_offers is None  # Amadeus not configured
    names = [h.name for h in res.hotels]
    assert "Hotel Paris" in names
    assert "Grand Way Hotel" in names


def test_search_respects_limit(ls):
    _set_http(ls, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    res = ls.search("Paris", limit=1)
    assert res.total == 2
    assert res.returned == 1


def test_search_empty_location_raises(ls):
    with pytest.raises(LetsFSError, match="location is required"):
        ls.search("")


def test_search_amadeus_not_configured_note(ls):
    _set_http(ls, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    res = ls.search("Paris")
    assert res.amadeus_offers is None
    assert "LETSFS_AMADEUS_KEY" in res.pricing_note


def test_search_amadeus_configured_but_no_dates(ls_amad):
    _set_http(ls_amad, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    res = ls_amad.search("PAR")
    assert res.amadeus_offers == []
    assert res.amadeus_error is not None
    assert "checkin/checkout" in res.amadeus_error


def test_search_amadeus_with_dates_fetches_offers(ls_amad):
    # GET sequence: Nominatim, Amadeus hotel list, Amadeus offers.
    # POST sequence: Overpass, Amadeus OAuth.
    amadeus_hotel_list = {"data": [{"hotelId": "AMAD1", "name": "Hotel Paris"}]}
    amadeus_offers = {
        "data": [
            {
                "hotel": {"hotelId": "AMAD1", "name": "Hotel Paris", "chainCode": "X"},
                "offers": [
                    {
                        "id": "o1",
                        "checkInDate": "2026-07-13",
                        "checkOutDate": "2026-07-20",
                        "room": {"typeEstimated": {"category": "STANDARD"}},
                        "price": {"currency": "EUR", "total": "320.00"},
                    }
                ],
            }
        ]
    }
    _set_http(
        ls_amad,
        get=[NOMINATIM_PARIS, amadeus_hotel_list, amadeus_offers],
        post=[OVERPASS_PARIS, {"access_token": "tok-123", "expires_in": 1800}],
    )
    res = ls_amad.search("PAR", checkin="2026-07-13", checkout="2026-07-20", adults=1)
    assert res.amadeus_offers is not None
    assert len(res.amadeus_offers) == 1
    offer = res.amadeus_offers[0]
    assert isinstance(offer, AmadeusOffer)
    assert offer.hotel_id == "AMAD1"
    assert offer.price_total == 320.0
    assert offer.currency == "EUR"
    # Best-effort price attachment: the OSM hotel "Hotel Paris" should now be priced.
    paris_hotel = next(h for h in res.hotels if h.name == "Hotel Paris")
    assert paris_hotel.price == 320.0
    assert paris_hotel.currency == "EUR"
    assert paris_hotel.pricing_source == "amadeus"


def test_search_amadeus_no_hotels_for_city(ls_amad):
    """Plain city name → Amadeus returns no hotels → OSM results still returned."""
    _set_http(
        ls_amad,
        get=[NOMINATIM_PARIS, {"data": []}],  # Nominatim, then empty Amadeus list
        post=[OVERPASS_PARIS, {"access_token": "tok", "expires_in": 1800}],
    )
    res = ls_amad.search("Paris", checkin="2026-07-13", checkout="2026-07-20")
    # OSM discovery still works.
    assert res.returned == 2
    assert res.amadeus_offers == []
    assert res.amadeus_error is not None
    assert "IATA city code" in res.amadeus_error


def test_search_bad_date_format_raises(ls_amad):
    _set_http(ls_amad, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    with pytest.raises(LetsFSError, match="YYYY-MM-DD"):
        ls_amad.search("PAR", checkin="07/13/2026", checkout="2026-07-20")


def test_search_checkout_before_checkin_raises(ls_amad):
    _set_http(ls_amad, get=NOMINATIM_PARIS, post=OVERPASS_PARIS)
    with pytest.raises(LetsFSError, match="must be after"):
        ls_amd_search(ls_amad, "2026-07-20", "2026-07-13")


def ls_amd_search(ls, checkin, checkout):
    return ls.search("PAR", checkin=checkin, checkout=checkout)


# ── get_hotel_details ─────────────────────────────────────────────────────

def test_get_hotel_details_success(ls):
    el = {
        "type": "way", "id": 42, "center": {"lat": 1.0, "lon": 2.0},
        "tags": {"name": "Detail Hotel", "internet_access": "wlan"},
    }
    _set_http(ls, post={"elements": [el]})
    d = ls.get_hotel_details(42, "way")
    assert isinstance(d, HotelDetails)
    assert d.osm_id == "42"
    assert d.osm_type == "way"
    assert d.name == "Detail Hotel"
    assert d.tags.get("internet_access") == "wlan"


def test_get_hotel_details_no_match_raises(ls):
    _set_http(ls, post={"elements": []})
    with pytest.raises(LetsFSError, match="No OSM element"):
        ls.get_hotel_details(999, "node")


def test_get_hotel_details_bad_type_raises(ls):
    with pytest.raises(LetsFSError, match="osm_type"):
        ls.get_hotel_details(1, "building")


def test_get_hotel_details_bad_id_raises(ls):
    with pytest.raises(LetsFSError, match="osm_id"):
        ls.get_hotel_details("abc", "node")


# ── Overpass query builder ────────────────────────────────────────────────

def test_hotels_by_bbox_query_shape(ls):
    q = ls._hotels_by_bbox_query("s,w,n,e")
    assert '[out:json]' in q
    assert 'node["tourism"="hotel"](s,w,n,e)' in q
    assert 'way["tourism"="hotel"](s,w,n,e)' in q
    assert 'relation["tourism"="hotel"](s,w,n,e)' in q
    assert 'out center tags' in q


# ── Bounding-box conversion (end-to-end through search) ──────────────────

def test_search_passes_overpass_bbox_order(ls, monkeypatch):
    """Nominatim bb [s,n,w,e] must be reordered to [s,w,n,e] for Overpass."""
    captured = {}

    def fake_run_overpass(query):
        captured["query"] = query
        return OVERPASS_PARIS["elements"]

    ls._run_overpass = fake_run_overpass  # type: ignore[assignment]
    _set_http(ls, get=NOMINATIM_PARIS)
    ls.search("Paris")
    # Nominatim bb = ["48.8156","48.9016","2.2241","2.4699"] (s,n,w,e)
    # Overpass should get s,w,n,e = 48.8156,2.2241,48.9016,2.4699
    assert "(48.8156,2.2241,48.9016,2.4699)" in captured["query"]


# ── Amadeus price attachment heuristic ────────────────────────────────────

def test_attach_amadeus_prices_exact_name_match(ls_amad):
    h = Hotel(osm_id="1", osm_type="node", name="Grand Hotel")
    offer = AmadeusOffer(
        hotel_id="A1", hotel_name="Grand Hotel",
        price_total=100.0, currency="EUR",
    )
    ls_amad._attach_amadeus_prices([h], [offer], "EUR")
    assert h.price == 100.0
    assert h.currency == "EUR"
    assert h.pricing_source == "amadeus"


def test_attach_amadeus_prices_picks_cheapest(ls_amad):
    h = Hotel(osm_id="1", osm_type="node", name="Grand Hotel")
    offers = [
        AmadeusOffer(hotel_id="A", hotel_name="Grand Hotel", price_total=200.0, currency="EUR"),
        AmadeusOffer(hotel_id="B", hotel_name="Grand Hotel", price_total=100.0, currency="EUR"),
    ]
    ls_amad._attach_amadeus_prices([h], offers, "EUR")
    assert h.price == 100.0  # cheaper one wins


def test_attach_amadeus_prices_no_match_leaves_none(ls_amad):
    h = Hotel(osm_id="1", osm_type="node", name="Unknown Hotel")
    offer = AmadeusOffer(
        hotel_id="A1", hotel_name="Other Hotel",
        price_total=100.0, currency="EUR",
    )
    ls_amd = ls_amad
    ls_amd._attach_amadeus_prices([h], [offer], "EUR")
    assert h.price is None
    assert h.pricing_source == "osm_only"
