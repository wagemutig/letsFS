"""Data models for the letsFS SDK — lightweight, no pydantic dependency.

All models are plain dataclasses with ``from_dict`` classmethods so they can be
built directly from the raw JSON returned by Nominatim / Overpass / Amadeus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ── Location (Nominatim) ──────────────────────────────────────────────────

@dataclass
class LocationResult:
    """A geocoded location returned by Nominatim.

    ``boundingbox`` is Nominatim's ordering: ``[south, north, west, east]``.
    Use ``overpass_bbox`` to get the ``south,west,north,east`` form that the
    Overpass API expects.
    """

    lat: float
    lon: float
    boundingbox: list[str]  # [south, north, west, east]
    display_name: str
    type: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "LocationResult":
        bb = d.get("boundingbox") or []
        try:
            lat = float(d.get("lat", 0) or 0)
            lon = float(d.get("lon", 0) or 0)
        except (TypeError, ValueError):
            lat, lon = 0.0, 0.0
        return cls(
            lat=lat,
            lon=lon,
            boundingbox=[str(x) for x in bb],
            display_name=d.get("display_name", ""),
            type=d.get("type", "") or d.get("class", "") or "",
            raw=dict(d),
        )

    @property
    def overpass_bbox(self) -> str:
        """Return the bounding box in Overpass order: ``south,west,north,east``.

        Nominatim returns ``[south, north, west, east]``; Overpass wants
        ``south,west,north,east``.
        """
        if len(self.boundingbox) != 4:
            return ""
        south, north, west, east = self.boundingbox
        return f"{south},{west},{north},{east}"


# ── Hotel (Overpass / OSM) ────────────────────────────────────────────────

@dataclass
class Hotel:
    """A single hotel discovered from OpenStreetMap.

    ``price`` and ``currency`` are populated only when Amadeus pricing was
    successfully matched to this hotel; otherwise ``price`` is ``None`` and
    ``pricing_source`` is ``"osm_only"``.
    """

    osm_id: str
    osm_type: str  # "node" | "way" | "relation"
    name: str
    stars: Optional[str] = None
    address: str = ""
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    rooms: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    tags: dict = field(default_factory=dict)
    price: Optional[float] = None
    currency: Optional[str] = None
    pricing_source: str = "osm_only"

    @classmethod
    def from_osm_element(cls, el: dict) -> "Hotel":
        """Build a Hotel from a single Overpass element.

        ``el`` should look like::

            {"type": "node", "id": 12345, "lat": 1.23, "lon": 4.56,
             "tags": {"name": "...", "stars": "4", ...}}

        For ``way``/``relation`` elements, the center lat/lon lives in
        ``el["center"]``.
        """
        tags = el.get("tags") or {}
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None and isinstance(el.get("center"), dict):
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")

        housenumber = tags.get("addr:housenumber")
        street = tags.get("addr:street")
        addr_parts = [p for p in (housenumber, street) if p]
        address = " ".join(addr_parts).strip() if addr_parts else tags.get("addr:full", "")

        name = tags.get("name") or tags.get("name:en") or ""

        return cls(
            osm_id=str(el.get("id", "")),
            osm_type=str(el.get("type", "")),
            name=name,
            stars=tags.get("stars"),
            address=address,
            city=tags.get("addr:city"),
            phone=tags.get("phone") or tags.get("contact:phone"),
            email=tags.get("contact:email") or tags.get("email"),
            website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
            rooms=tags.get("rooms"),
            lat=lat,
            lon=lon,
            tags=dict(tags),
            price=None,
            currency=None,
            pricing_source="osm_only",
        )

    @property
    def stars_int(self) -> Optional[int]:
        """Best-effort integer star rating, or ``None``."""
        if self.stars is None:
            return None
        try:
            return int(str(self.stars).strip())
        except (TypeError, ValueError):
            return None

    def summary(self) -> str:
        """One-line summary like ``Grand Hotel | ★4 | 12 Main St | €120.00``."""
        star = f"★{self.stars}" if self.stars else "—"
        price = ""
        if self.price is not None and self.currency:
            price = f" | {self.currency} {self.price:.2f}"
        elif self.price is not None:
            price = f" | {self.price:.2f}"
        addr = self.address or "—"
        return f"{self.name or '(unnamed)'} | {star} | {addr}{price}"

    def to_dict(self) -> dict:
        return {
            "osm_id": self.osm_id,
            "osm_type": self.osm_type,
            "name": self.name,
            "stars": self.stars,
            "address": self.address,
            "city": self.city,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "rooms": self.rooms,
            "lat": self.lat,
            "lon": self.lon,
            "tags": self.tags,
            "price": self.price,
            "currency": self.currency,
            "pricing_source": self.pricing_source,
        }


# ── Hotel details (raw OSM element) ───────────────────────────────────────

@dataclass
class HotelDetails:
    """The complete OSM record for a single hotel.

    ``tags`` is the full, raw OSM tag dict — use this for amenities not
    summarized on :class:`Hotel` (e.g. ``internet_access``, ``wheelchair``,
    ``operator``).
    """

    osm_id: str
    osm_type: str
    name: str
    stars: Optional[str] = None
    address: str = ""
    phone: Optional[str] = None
    website: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    tags: dict = field(default_factory=dict)

    @classmethod
    def from_osm_element(cls, el: dict) -> "HotelDetails":
        tags = el.get("tags") or {}
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None and isinstance(el.get("center"), dict):
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")

        housenumber = tags.get("addr:housenumber")
        street = tags.get("addr:street")
        addr_parts = [p for p in (housenumber, street) if p]
        address = " ".join(addr_parts).strip() if addr_parts else tags.get("addr:full", "")

        return cls(
            osm_id=str(el.get("id", "")),
            osm_type=str(el.get("type", "")),
            name=tags.get("name") or tags.get("name:en") or "",
            stars=tags.get("stars"),
            address=address,
            phone=tags.get("phone") or tags.get("contact:phone"),
            website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
            lat=lat,
            lon=lon,
            tags=dict(tags),
        )

    def to_dict(self) -> dict:
        return {
            "osm_id": self.osm_id,
            "osm_type": self.osm_type,
            "name": self.name,
            "stars": self.stars,
            "address": self.address,
            "phone": self.phone,
            "website": self.website,
            "lat": self.lat,
            "lon": self.lon,
            "tags": self.tags,
        }


# ── Amadeus live-pricing offer ────────────────────────────────────────────

@dataclass
class AmadeusOffer:
    """A live hotel offer returned by the Amadeus Hotel Search API.

    Amadeus uses its own hotel IDs — there is no reliable mapping back to OSM
    ``osm_id``. Correlate to OSM hotels by best-effort name matching only.
    """

    hotel_id: str
    hotel_name: str
    chain_code: Optional[str] = None
    price_total: Optional[float] = None
    currency: Optional[str] = None
    room_type: Optional[str] = None
    check_in: str = ""
    check_out: str = ""

    @classmethod
    def from_amadeus_offer(cls, hotel: dict, offer: dict, checkin: str, checkout: str) -> "AmadeusOffer":
        price = (offer.get("price") or {}) if isinstance(offer, dict) else {}
        room = (offer.get("room") or {}) if isinstance(offer, dict) else {}
        type_est = (room.get("typeEstimated") or {}) if isinstance(room, dict) else {}
        total = price.get("total")
        try:
            total_f = float(total) if total is not None else None
        except (TypeError, ValueError):
            total_f = None
        return cls(
            hotel_id=str(hotel.get("hotelId", "")),
            hotel_name=str(hotel.get("name", "")),
            chain_code=hotel.get("chainCode"),
            price_total=total_f,
            currency=price.get("currency"),
            room_type=type_est.get("category"),
            check_in=str(offer.get("checkInDate", checkin)) if isinstance(offer, dict) else checkin,
            check_out=str(offer.get("checkOutDate", checkout)) if isinstance(offer, dict) else checkout,
        )

    def to_dict(self) -> dict:
        return {
            "hotel_id": self.hotel_id,
            "hotel_name": self.hotel_name,
            "chain_code": self.chain_code,
            "price_total": self.price_total,
            "currency": self.currency,
            "room_type": self.room_type,
            "check_in": self.check_in,
            "check_out": self.check_out,
        }


# ── Search result ─────────────────────────────────────────────────────────

@dataclass
class HotelSearchResult:
    """Full hotel search result.

    When Amadeus is configured and ``checkin``/``checkout`` are supplied,
    ``amadeus_offers`` holds live-priced offers (separate from the OSM
    ``hotels`` list). ``amadeus_error`` explains why pricing may be missing
    even when Amadeus is configured (e.g. plain city name instead of an IATA
    code).
    """

    total: int
    hotels: list[Hotel] = field(default_factory=list)
    location: str = ""
    search_id: str = ""
    resolved: Optional[LocationResult] = None
    pricing_source: str = "openstreetmap"
    pricing_note: str = ""
    amadeus_offers: Optional[list[AmadeusOffer]] = None
    amadeus_error: Optional[str] = None

    @property
    def returned(self) -> int:
        return len(self.hotels)

    @property
    def cheapest(self) -> Optional[Hotel]:
        """Cheapest hotel with a known price, or ``None``."""
        priced = [h for h in self.hotels if h.price is not None]
        if not priced:
            return None
        # Filtered to priced hotels above; cast appeases the type checker.
        return min(priced, key=lambda h: float(h.price or 0.0))

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "location": self.location,
            "total_found": self.total,
            "returned": self.returned,
            "hotels": [h.to_dict() for h in self.hotels],
            "pricing_source": self.pricing_source,
            "pricing_note": self.pricing_note,
            "search_id": self.search_id,
        }
        if self.resolved is not None:
            d["resolved"] = {
                "display_name": self.resolved.display_name,
                "lat": self.resolved.lat,
                "lon": self.resolved.lon,
                "boundingbox": self.resolved.boundingbox,
            }
        if self.amadeus_offers is not None:
            d["amadeus_offers"] = [o.to_dict() for o in self.amadeus_offers]
        if self.amadeus_error is not None:
            d["amadeus_error"] = self.amadeus_error
        return d
