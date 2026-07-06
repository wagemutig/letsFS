"""letsFS — Hotel search SDK for AI agents.

Free, worldwide hotel discovery via OpenStreetMap (Nominatim + Overpass).
Optional live pricing via Amadeus when credentials are configured.

Quick start
-----------
>>> from letsfs import LetsFS
>>> ls = LetsFS()                       # OSM-only, no API key needed
>>> res = ls.search("Bali", limit=20)
>>> for h in res.hotels:
...     print(h.summary())
Grand Hyatt Bali | ★5 | ...

With Amadeus live pricing::

    ls = LetsFS(amadeus_key="...", amadeus_secret="...")
    res = ls.search("PAR", checkin="2026-07-13", checkout="2026-07-20", adults=1)
"""

from .client import LetsFS, LetsFSConfig, LetsFSError
from .config import Config
from .models import (
    AmadeusOffer,
    Hotel,
    HotelDetails,
    HotelSearchResult,
    LocationResult,
)

__version__ = "0.1.0"

__all__ = [
    "LetsFS",
    "LetsFSConfig",
    "LetsFSError",
    "Config",
    "AmadeusOffer",
    "Hotel",
    "HotelDetails",
    "HotelSearchResult",
    "LocationResult",
    "__version__",
]
