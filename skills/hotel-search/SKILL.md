---
name: hotel-search
description: Search hotels worldwide via OpenStreetMap (free, no API key) with optional Amadeus live pricing. Use when the user asks to find, compare, or book hotels.
---

# Hotel Search Skill (letsFS)

## When to use

- User asks to "find hotels in [city]"
- User needs hotel recommendations for a trip
- User wants to compare hotel prices
- User asks "where should I stay in [location]"

## MCP Tools (if letsfs MCP server is connected)

- `search_hotels` — Search by location, dates, guests. Returns name, stars, address, phone, website, price (if Amadeus configured).
- `resolve_location` — Geocode a city name.
- `get_hotel_details` — Full OSM tags for a hotel.
- `load_resources` — Load the hotel search guide.

## Python SDK (fallback)

```python
from letsfs import LetsFS

ls = LetsFS()
hotels = ls.search("Bali", limit=20)
for h in hotels:
    print(f"{'★'*int(h.stars) if h.stars else 'N/A'} {h.name} — {h.address} — {h.phone or ''}")
```

## CLI

```bash
letsfs search "Bali" --limit 20
letsfs location "Denpasar"
letsfs hotel 58467591 node
```

## Notes

- Without Amadeus credentials, you get hotel discovery (name, stars, contact) but NOT real-time pricing.
- OSM data quality varies by region — some hotels may have incomplete tags.
- Nominatim is rate-limited (1 req/sec). Don't batch geocode.
- For pricing, set `LETSFS_AMADEUS_KEY` and `LETSFS_AMADEUS_SECRET` env vars.
