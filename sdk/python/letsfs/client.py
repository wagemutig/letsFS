"""letsFS main client.

Hotel search via two complementary data sources:

1. **OpenStreetMap (Nominatim + Overpass)** — DEFAULT, free, no API key.
   Geocode the location with Nominatim, discover hotels in the bounding box
   with Overpass. Works worldwide. Does NOT include real-time pricing.

2. **Amadeus Hotel Search** — OPTIONAL. When ``amadeus_key`` + ``amadeus_secret``
   are configured AND ``checkin``/``checkout`` are supplied, a separate
   ``amadeus_offers`` array with live prices is included. Amadeus pricing
   needs an **IATA city code** (e.g. ``PAR``, ``LON``, ``NYC``) as the
   ``location`` — a plain city name will not match Amadeus.

All HTTP is done with :mod:`urllib.request` (stdlib) — no external runtime
dependencies for core search.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional, Union

from .config import Config
from .models import (
    AmadeusOffer,
    Hotel,
    HotelDetails,
    HotelSearchResult,
    LocationResult,
)

# Re-export so callers can do ``from letsfs.client import LetsFSConfig`` etc.
LetsFSConfig = Config

__all__ = ["LetsFS", "LetsFSConfig"]


# ── Helpers ───────────────────────────────────────────────────────────────

_VALID_OSM_TYPES = {"node", "way", "relation"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OSM_ID_RE = re.compile(r"^\d+$")


class LetsFSError(Exception):
    """Raised for unrecoverable letsFS errors (bad params, network failure)."""


# ── Main client ───────────────────────────────────────────────────────────

class LetsFS:
    """letsFS hotel search client.

    Usage
    -----
    >>> from letsfs import LetsFS
    >>> ls = LetsFS()                       # OSM-only mode, no API key needed
    >>> res = ls.search("Bali", limit=20)
    >>> for h in res.hotels:
    ...     print(h.summary())
    Grand Hyatt Bali | ★5 | ...

    With optional Amadeus live pricing::

        ls = LetsFS(amadeus_key="...", amadeus_secret="...")
        res = ls.search("PAR", checkin="2026-07-13", checkout="2026-07-20", adults=1)
        for offer in res.amadeus_offers or []:
            print(offer.hotel_name, offer.price_total, offer.currency)
    """

    def __init__(
        self,
        amadeus_key: Optional[str] = None,
        amadeus_secret: Optional[str] = None,
        amadeus_base: Optional[str] = None,
        nominatim_url: Optional[str] = None,
        overpass_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        config: Optional[Config] = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = Config.load(
                amadeus_key=amadeus_key,
                amadeus_secret=amadeus_secret,
                amadeus_base=amadeus_base,
                nominatim_url=nominatim_url,
                overpass_url=overpass_url,
                user_agent=user_agent,
                timeout=timeout,
            )
        # Cached Amadeus OAuth token: {"token": str, "expires_at": float}.
        self._amadeus_token: Optional[dict[str, Any]] = None
        # Last time we called Nominatim (for rate limiting).
        self._last_nominatim_call: float = 0.0

    # ── Public surface ───────────────────────────────────────────────

    @property
    def amadeus_enabled(self) -> bool:
        return self.config.amadeus_enabled

    def resolve_location(self, query: str) -> LocationResult:
        """Geocode a city/place name to lat/lon + bounding box via Nominatim.

        Raises :class:`LetsFSError` on network failure or no match.
        """
        if not query or not str(query).strip():
            raise LetsFSError("query is required")
        url = (
            f"{self.config.nominatim_url}/search"
            f"?q={urllib.parse.quote(str(query))}&format=json&limit=1"
        )
        data = self._http_get_json(
            url,
            headers={"Accept": "application/json"},
            polite_nominatim=True,
        )
        if not isinstance(data, list) or not data:
            raise LetsFSError(f'No geocoding result for location: "{query}"')
        return LocationResult.from_dict(data[0])

    def search(
        self,
        location: str,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: int = 1,
        rooms: int = 1,
        limit: int = 20,
        currency: str = "EUR",
    ) -> HotelSearchResult:
        """Search hotels in ``location``.

        Parameters
        ----------
        location
            City name (e.g. ``"Paris"``) for free OSM discovery, **or** an
            IATA city code (e.g. ``"PAR"``) if you also want Amadeus live
            pricing.
        checkin, checkout
            ``YYYY-MM-DD`` dates. Required for Amadeus pricing; ignored by
            OSM discovery.
        adults
            Number of adults (default ``1``). Used only for Amadeus pricing.
        rooms
            Number of rooms (default ``1``). Used only for Amadeus pricing.
        limit
            Max hotels to return (default ``20``).
        currency
            Currency code for Amadeus pricing (default ``"EUR"``).

        Returns
        -------
        HotelSearchResult
        """
        location = (location or "").strip()
        if not location:
            raise LetsFSError("location is required")
        if limit < 1:
            limit = 1

        # 1) Geocode via Nominatim.
        try:
            geo = self.resolve_location(location)
        except LetsFSError:
            raise

        bbox = geo.overpass_bbox
        if not bbox:
            raise LetsFSError(
                f'Nominatim returned no bounding box for location: "{location}"'
            )

        # 2) Overpass hotel discovery.
        query = self._hotels_by_bbox_query(bbox)
        try:
            elements = self._run_overpass(query)
        except LetsFSError:
            raise

        all_hotels = [
            Hotel.from_osm_element(el)
            for el in elements
        ]
        # Drop unnamed hotels — they are not useful in search results.
        all_hotels = [h for h in all_hotels if h.name]
        hotels = all_hotels[:limit]

        pricing_note = (
            "OSM discovery does not include prices. See amadeus_offers for "
            "live pricing (if available)."
            if self.amadeus_enabled
            else "OSM discovery does not include prices. Set "
            "LETSFS_AMADEUS_KEY + LETSFS_AMADEUS_SECRET and provide "
            "checkin/checkout dates for live Amadeus pricing."
        )

        result = HotelSearchResult(
            total=len(all_hotels),
            hotels=hotels,
            location=location,
            search_id=uuid.uuid4().hex,
            resolved=geo,
            pricing_source="openstreetmap",
            pricing_note=pricing_note,
        )

        # 3) Optional Amadeus pricing enrichment.
        amadeus_offers: Optional[list[AmadeusOffer]] = None
        amadeus_error: Optional[str] = None
        if self.amadeus_enabled:
            if checkin and checkout:
                self._validate_dates(checkin, checkout)
                offers, err = self._fetch_amadeus_offers(
                    location, checkin, checkout, adults, rooms, currency, limit
                )
                amadeus_offers = offers
                amadeus_error = err
                # Best-effort: attach cheapest matching price to OSM hotels.
                self._attach_amadeus_prices(hotels, offers or [], currency)
            else:
                amadeus_offers = []
                amadeus_error = (
                    "Amadeus configured but checkin/checkout dates not "
                    "provided — pricing skipped. Pass both checkin and "
                    "checkout (YYYY-MM-DD) for live prices."
                )

        result.amadeus_offers = amadeus_offers
        result.amadeus_error = amadeus_error
        return result

    def get_hotel_details(self, osm_id: Union[str, int], osm_type: str) -> HotelDetails:
        """Fetch the complete OSM record for a single hotel.

        Parameters
        ----------
        osm_id
            Numeric OSM element ID (as returned by :meth:`search`).
        osm_type
            ``"node"``, ``"way"``, or ``"relation"``.

        Raises :class:`LetsFSError` on bad input or no match.
        """
        osm_type = (osm_type or "").strip().lower()
        osm_id_s = str(osm_id).strip()
        if osm_type not in _VALID_OSM_TYPES:
            raise LetsFSError(
                f'Invalid osm_type "{osm_type}" — must be one of: '
                f"{', '.join(sorted(_VALID_OSM_TYPES))}."
            )
        if not _OSM_ID_RE.match(osm_id_s):
            raise LetsFSError(f'Invalid osm_id "{osm_id}" — must be numeric.')

        query = (
            f"[out:json][timeout:{self.config.overpass_timeout_s}];\n"
            f"{osm_type}({osm_id_s});\n"
            "out center tags;\n"
        )
        elements = self._run_overpass(query)
        if not elements:
            raise LetsFSError(
                f"No OSM element found for osm_type={osm_type} osm_id={osm_id_s}"
            )
        return HotelDetails.from_osm_element(elements[0])

    # ── Amadeus internals ────────────────────────────────────────────

    def _fetch_amadeus_offers(
        self,
        city_code: str,
        checkin: str,
        checkout: str,
        adults: int,
        rooms: int,
        currency: str,
        limit: int,
    ) -> tuple[list[AmadeusOffer], Optional[str]]:
        """Fetch live Amadeus hotel offers. Returns ``(offers, error)``.

        On any failure, returns ``([], "<message>")`` so callers can still get
        OSM discovery results — Amadeus is best-effort enrichment.
        """
        code = city_code.strip().upper()

        # 1) Hotel list by city.
        list_path = (
            "/v1/reference-data/locations/hotels/by-city?cityCode="
            + urllib.parse.quote(code)
        )
        list_res = self._amadeus_get(list_path)
        if not list_res["ok"]:
            return [], f"Amadeus hotel list: {list_res['error']}"
        list_data = list_res["data"] or {}
        hotel_entries = list_data.get("data") or []
        hotel_ids = [h.get("hotelId") for h in hotel_entries if h.get("hotelId")]
        if not hotel_ids:
            return [], (
                f'Amadeus returned no hotels for city code "{code}". '
                "Pass an IATA city code (e.g. PAR, LON, NYC) as the location "
                "for pricing."
            )

        # 2) Hotel offers (v3). Cap the ID batch.
        batch_size = max(1, min(limit, 100))
        id_batch = hotel_ids[:batch_size]
        offers_path = (
            "/v3/shopping/hotel-offers?hotelIds="
            + urllib.parse.quote(",".join(id_batch))
            + f"&checkInDate={urllib.parse.quote(checkin)}"
            + f"&checkOutDate={urllib.parse.quote(checkout)}"
            + f"&adults={int(adults)}"
            + f"&roomQuantity={int(rooms)}"
            + f"&currency={urllib.parse.quote(currency)}"
        )
        off_res = self._amadeus_get(offers_path)
        if not off_res["ok"]:
            return [], f"Amadeus hotel offers: {off_res['error']}"
        off_data = off_res["data"] or {}

        offers: list[AmadeusOffer] = []
        for entry in off_data.get("data") or []:
            hotel = entry.get("hotel") or {}
            for o in entry.get("offers") or []:
                offers.append(
                    AmadeusOffer.from_amadeus_offer(hotel, o, checkin, checkout)
                )
                if len(offers) >= limit:
                    break
            if len(offers) >= limit:
                break
        return offers, None

    def _attach_amadeus_prices(
        self, hotels: list[Hotel], offers: list[AmadeusOffer], currency: str
    ) -> None:
        """Best-effort: attach the cheapest matching Amadeus price to each
        OSM hotel, matched on normalized hotel name.

        OSM and Amadeus use different hotel IDs, so name matching is the only
        available heuristic. This is intentionally conservative — only
        case-insensitive, punctuation-insensitive substring equality is used.
        """
        if not offers or not hotels:
            return

        def norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

        # Pre-compute normalized Amadeus offers, sorted cheapest first.
        normed = sorted(
            [
                (norm(o.hotel_name), o)
                for o in offers
                if o.price_total is not None
            ],
            key=lambda t: t[1].price_total or 0.0,
        )

        for h in hotels:
            hn = norm(h.name)
            if not hn:
                continue
            # Prefer an exact normalized match; fall back to substring.
            match = None
            for nn, o in normed:
                if nn == hn:
                    match = o
                    break
            if match is None:
                for nn, o in normed:
                    if hn and (hn in nn or nn in hn):
                        match = o
                        break
            if match is not None and match.price_total is not None:
                h.price = match.price_total
                h.currency = match.currency or currency
                h.pricing_source = "amadeus"

    def _amadeus_get(self, path: str) -> dict[str, Any]:
        """GET an Amadeus API path with a cached bearer token.

        Returns ``{"ok": bool, "data"?: dict, "error"?: str}``.
        """
        token_res = self._get_amadeus_token()
        if not token_res["ok"]:
            return token_res  # already {"ok": False, "error": ...}
        token = token_res["token"]
        url = f"{self.config.amadeus_base}{path}"
        try:
            data = self._http_get_json(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.amadeus+json",
                },
                polite_nominatim=False,
            )
        except LetsFSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "data": data}

    def _get_amadeus_token(self) -> dict[str, Any]:
        """Get a cached Amadeus OAuth token, refreshing as needed.

        Returns ``{"ok": bool, "token"?: str, "error"?: str}``.
        """
        if self._amadeus_token and time.time() < self._amadeus_token["expires_at"]:
            return {"ok": True, "token": self._amadeus_token["token"]}

        body = (
            "grant_type=client_credentials"
            f"&client_id={urllib.parse.quote(self.config.amadeus_key)}"
            f"&client_secret={urllib.parse.quote(self.config.amadeus_secret)}"
        )
        url = f"{self.config.amadeus_base}/v1/security/oauth2/token"
        try:
            data = self._http_post_json(
                url,
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                polite_nominatim=False,
            )
        except LetsFSError as e:
            self._amadeus_token = None
            return {"ok": False, "error": str(e)}

        access_token = data.get("access_token")
        if not access_token:
            self._amadeus_token = None
            return {"ok": False, "error": "Amadeus OAuth response missing access_token."}
        expires_in = data.get("expires_in", 1800)
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            expires_in = 1800
        # Refresh 60s before expiry.
        self._amadeus_token = {
            "token": access_token,
            "expires_at": time.time() + max(1, expires_in - 60),
        }
        return {"ok": True, "token": access_token}

    # ── Overpass (OSM) internals ────────────────────────────────────

    def _hotels_by_bbox_query(self, bbox: str) -> str:
        """Build the Overpass hotel-discovery query for a bounding box."""
        return (
            f"[out:json][timeout:{self.config.overpass_timeout_s}];\n"
            "(\n"
            f'  node["tourism"="hotel"]({bbox});\n'
            f'  way["tourism"="hotel"]({bbox});\n'
            f'  relation["tourism"="hotel"]({bbox});\n'
            ");\n"
            f"out center tags {self.config.overpass_fetch_cap};\n"
        )

    def _run_overpass(self, query: str) -> list[dict]:
        """POST a query to the Overpass API; return the ``elements`` array."""
        body = "data=" + urllib.parse.quote(query)
        try:
            data = self._http_post_json(
                self.config.overpass_url,
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                polite_nominatim=False,
            )
        except LetsFSError:
            raise
        elements = data.get("elements") or []
        return elements if isinstance(elements, list) else []

    # ── HTTP plumbing (urllib, no `requests`) ───────────────────────

    def _rate_limit_nominatim(self) -> None:
        """Enforce a polite delay between Nominatim calls."""
        if self.config.nominatim_rate_ms <= 0:
            return
        elapsed = time.time() - self._last_nominatim_call
        wait = (self.config.nominatim_rate_ms / 1000.0) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_nominatim_call = time.time()

    def _http_get_json(self, url: str, headers: Optional[dict] = None, *, polite_nominatim: bool = False) -> Any:
        """GET ``url`` and parse JSON. Raises :class:`LetsFSError` on failure."""
        if polite_nominatim:
            self._rate_limit_nominatim()
        req_headers = {"User-Agent": self.config.user_agent}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers, method="GET")
        return self._do_request(req, url)

    def _http_post_json(self, url: str, body: str, headers: Optional[dict] = None, *, polite_nominatim: bool = False) -> Any:
        """POST ``body`` to ``url`` and parse JSON. Raises :class:`LetsFSError`."""
        if polite_nominatim:
            self._rate_limit_nominatim()
        req_headers = {"User-Agent": self.config.user_agent}
        if headers:
            req_headers.update(headers)
        data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        return self._do_request(req, url)

    def _do_request(self, req: urllib.request.Request, url: str) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            msg = f"HTTP {e.code} for {url}"
            if detail:
                msg = f"{msg}: {detail}"
            raise LetsFSError(msg) from e
        except urllib.error.URLError as e:
            raise LetsFSError(f"Network error for {url}: {e.reason}") from e
        except Exception as e:
            raise LetsFSError(f"Request failed for {url}: {e}") from e

        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            # Non-JSON response — surface a short snippet for debugging.
            snippet = raw[:200].decode("utf-8", errors="replace")
            raise LetsFSError(
                f"Non-JSON response from {url}: {snippet!r}"
            ) from e

    # ── Validation helpers ──────────────────────────────────────────

    @staticmethod
    def _validate_dates(checkin: str, checkout: str) -> None:
        if not _DATE_RE.match(checkin):
            raise LetsFSError(
                f"checkin must be YYYY-MM-DD, got: {checkin!r}"
            )
        if not _DATE_RE.match(checkout):
            raise LetsFSError(
                f"checkout must be YYYY-MM-DD, got: {checkout!r}"
            )
        if checkout <= checkin:
            raise LetsFSError(
                f"checkout ({checkout}) must be after checkin ({checkin})"
            )
