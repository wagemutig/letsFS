"""Deterministic tests for letsFS models — no network required."""

from __future__ import annotations

from letsfs.models import (
    AmadeusOffer,
    Hotel,
    HotelDetails,
    HotelSearchResult,
    LocationResult,
)


# ── LocationResult ────────────────────────────────────────────────────────

def test_location_result_from_nominatim():
    """Nominatim returns boundingbox as [south, north, west, east]."""
    geo = LocationResult.from_dict(
        {
            "lat": "48.8566",
            "lon": "2.3522",
            "boundingbox": ["48.8156", "48.9016", "2.2241", "2.4699"],
            "display_name": "Paris, Île-de-France, France",
            "type": "city",
        }
    )
    assert geo.lat == 48.8566
    assert geo.lon == 2.3522
    assert geo.boundingbox == ["48.8156", "48.9016", "2.2241", "2.4699"]
    assert "Paris" in geo.display_name
    assert geo.type == "city"


def test_location_result_overpass_bbox_format():
    """Overpass wants south,west,north,east (not Nominatim's south,north,west,east)."""
    geo = LocationResult.from_dict(
        {
            "lat": "1", "lon": "2",
            "boundingbox": ["10", "20", "30", "40"],  # south, north, west, east
            "display_name": "X",
        }
    )
    # Expect south,west,north,east = 10,30,20,40
    assert geo.overpass_bbox == "10,30,20,40"


def test_location_result_bad_lat_does_not_raise():
    """Bad numeric input falls back to 0.0 instead of raising."""
    geo = LocationResult.from_dict(
        {"lat": "not-a-number", "lon": None, "boundingbox": [], "display_name": "X"}
    )
    assert geo.lat == 0.0
    assert geo.lon == 0.0
    assert geo.overpass_bbox == ""


# ── Hotel ─────────────────────────────────────────────────────────────────

def test_hotel_from_osm_node():
    el = {
        "type": "node",
        "id": 12345,
        "lat": 1.23,
        "lon": 4.56,
        "tags": {
            "name": "Grand Hotel",
            "stars": "5",
            "addr:housenumber": "12",
            "addr:street": "Main St",
            "addr:city": "Bali",
            "phone": "+62-123",
            "contact:email": "stay@grand.example",
            "website": "https://grand.example",
            "rooms": "200",
        },
    }
    h = Hotel.from_osm_element(el)
    assert h.osm_id == "12345"
    assert h.osm_type == "node"
    assert h.name == "Grand Hotel"
    assert h.stars == "5"
    assert h.stars_int == 5
    assert h.address == "12 Main St"
    assert h.city == "Bali"
    assert h.phone == "+62-123"
    assert h.email == "stay@grand.example"
    assert h.website == "https://grand.example"
    assert h.rooms == "200"
    assert h.lat == 1.23
    assert h.lon == 4.56
    assert h.price is None
    assert h.pricing_source == "osm_only"


def test_hotel_from_osm_way_uses_center():
    """way/relation elements carry lat/lon in el['center'], not on the element."""
    el = {
        "type": "way",
        "id": 67890,
        "center": {"lat": 50.0, "lon": 60.0},
        "tags": {"name": "Way Hotel"},
    }
    h = Hotel.from_osm_element(el)
    assert h.lat == 50.0
    assert h.lon == 60.0
    assert h.osm_type == "way"


def test_hotel_address_falls_back_to_addr_full():
    el = {
        "type": "node", "id": 1, "lat": 0, "lon": 0,
        "tags": {"name": "X", "addr:full": "PO Box 99, Somewhere"},
    }
    h = Hotel.from_osm_element(el)
    assert h.address == "PO Box 99, Somewhere"


def test_hotel_name_falls_back_to_name_en():
    el = {"type": "node", "id": 1, "tags": {"name:en": "English Name"}}
    h = Hotel.from_osm_element(el)
    assert h.name == "English Name"


def test_hotel_stars_int_handles_garbage():
    el = {"type": "node", "id": 1, "tags": {"name": "X", "stars": "unknown"}}
    h = Hotel.from_osm_element(el)
    assert h.stars == "unknown"
    assert h.stars_int is None


def test_hotel_summary_with_price():
    h = Hotel(
        osm_id="1", osm_type="node", name="Grand", stars="5",
        address="12 Main St", price=120.0, currency="EUR",
    )
    assert h.summary() == "Grand | ★5 | 12 Main St | EUR 120.00"


def test_hotel_summary_without_price():
    h = Hotel(osm_id="1", osm_type="node", name="Grand", stars=None, address="")
    assert h.summary() == "Grand | — | —"


def test_hotel_to_dict_roundtrip():
    h = Hotel(osm_id="1", osm_type="node", name="Grand", stars="4", address="1 St")
    d = h.to_dict()
    assert d["osm_id"] == "1"
    assert d["name"] == "Grand"
    assert d["pricing_source"] == "osm_only"


# ── HotelDetails ──────────────────────────────────────────────────────────

def test_hotel_details_from_osm():
    el = {
        "type": "way", "id": 42, "center": {"lat": 1.0, "lon": 2.0},
        "tags": {
            "name": "Detail Hotel", "stars": "3",
            "addr:housenumber": "5", "addr:street": "Side Rd",
            "phone": "555", "website": "http://x",
            "internet_access": "wlan", "wheelchair": "yes",
        },
    }
    d = HotelDetails.from_osm_element(el)
    assert d.osm_id == "42"
    assert d.osm_type == "way"
    assert d.name == "Detail Hotel"
    assert d.stars == "3"
    assert d.address == "5 Side Rd"
    assert d.phone == "555"
    assert d.website == "http://x"
    assert d.lat == 1.0
    assert d.lon == 2.0
    # Full raw tag set is preserved.
    assert d.tags.get("internet_access") == "wlan"
    assert d.tags.get("wheelchair") == "yes"


# ── AmadeusOffer ──────────────────────────────────────────────────────────

def test_amadeus_offer_from_dict():
    hotel = {"hotelId": "AMAD123", "name": "Amadeus Grand", "chainCode": "AM"}
    offer = {
        "id": "offer-1",
        "checkInDate": "2026-07-13",
        "checkOutDate": "2026-07-20",
        "room": {"typeEstimated": {"category": "STANDARD"}},
        "price": {"currency": "EUR", "total": "540.00"},
    }
    o = AmadeusOffer.from_amadeus_offer(hotel, offer, "2026-07-13", "2026-07-20")
    assert o.hotel_id == "AMAD123"
    assert o.hotel_name == "Amadeus Grand"
    assert o.chain_code == "AM"
    assert o.price_total == 540.0
    assert o.currency == "EUR"
    assert o.room_type == "STANDARD"
    assert o.check_in == "2026-07-13"
    assert o.check_out == "2026-07-20"


def test_amadeus_offer_handles_missing_price():
    hotel = {"hotelId": "X", "name": "X"}
    offer = {"checkInDate": "2026-07-13", "checkOutDate": "2026-07-20"}
    o = AmadeusOffer.from_amadeus_offer(hotel, offer, "2026-07-13", "2026-07-20")
    assert o.price_total is None
    assert o.currency is None


# ── HotelSearchResult ─────────────────────────────────────────────────────

def test_search_result_cheapest():
    h1 = Hotel(osm_id="1", osm_type="node", name="A", price=100.0, currency="EUR")
    h2 = Hotel(osm_id="2", osm_type="node", name="B", price=50.0, currency="EUR")
    h3 = Hotel(osm_id="3", osm_type="node", name="C")  # no price
    res = HotelSearchResult(total=3, hotels=[h1, h2, h3])
    assert res.returned == 3
    assert res.cheapest is h2


def test_search_result_cheapest_none_when_unpriced():
    h = Hotel(osm_id="1", osm_type="node", name="A")
    res = HotelSearchResult(total=1, hotels=[h])
    assert res.cheapest is None


def test_search_result_to_dict_shape():
    h = Hotel(osm_id="1", osm_type="node", name="A", stars="4")
    res = HotelSearchResult(
        total=1, hotels=[h], location="Bali",
        pricing_source="openstreetmap", pricing_note="note",
    )
    d = res.to_dict()
    assert d["location"] == "Bali"
    assert d["total_found"] == 1
    assert d["returned"] == 1
    assert d["hotels"][0]["name"] == "A"
    assert d["pricing_source"] == "openstreetmap"
    assert d["pricing_note"] == "note"
    # amadeus_offers omitted when None.
    assert "amadeus_offers" not in d
