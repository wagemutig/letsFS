# letsFS Documentation

## Overview

letsFS is a hotel search tool for AI agents. It provides:

- **MCP Server** — stdio JSON-RPC server for Claude, Cursor, Windsurf, Hermes, and any MCP-compatible client
- **Python SDK** — programmatic hotel search client
- **CLI** — command-line hotel search

## Data Sources

### OpenStreetMap (Free, No Key)

- **Nominatim**: Geocodes city names to lat/lon + bounding box
- **Overpass API**: Queries OpenStreetMap for `tourism=hotel` nodes/ways/relations within a bounding box
- Returns: name, star rating, address, phone, website, email, coordinates
- Does NOT return: real-time pricing, availability, room types

### Amadeus (Optional, Free Sandbox)

- **OAuth2**: Client credentials flow → access token (cached with expiry)
- **Hotel List by City**: IATA city code → hotel property list
- **Hotel Offers**: hotelIds + dates + guests → real-time pricing and availability
- Requires: `LETSFS_AMADEUS_KEY` and `LETSFS_AMADEUS_SECRET` env vars

## Quick Start

### MCP Client Config

```json
{
  "mcpServers": {
    "letsfs": {
      "command": "npx",
      "args": ["-y", "letsfs-mcp"]
    }
  }
}
```

### Python

```python
from letsfs import LetsFS

ls = LetsFS()
hotels = ls.search("Bali", limit=10)
```

### CLI

```bash
letsfs search "Bali" --limit 10
```

## MCP Protocol

The server implements MCP over stdio (JSON-RPC 2.0):

- `initialize` → server info (`letsfs` v0.1.0)
- `tools/list` → 4 tools
- `tools/call` → execute a tool
- `resources/list` → 1 resource (`letsfs://guide`)
- `resources/read` → read the guide
- `ping` → health check

## Tools Reference

### search_hotels

Search for hotels in a location.

**Parameters:**
- `location` (string, required) — City or place name
- `checkin` (string, optional) — YYYY-MM-DD
- `checkout` (string, optional) — YYYY-MM-DD
- `adults` (int, default 1)
- `rooms` (int, default 1)
- `limit` (int, default 20)
- `currency` (string, default "EUR")

**Returns:** Array of hotels with name, stars, address, phone, website, lat, lon, osm_id, osm_type, price (if Amadeus).

### resolve_location

Geocode a place name.

**Parameters:**
- `query` (string, required)

**Returns:** lat, lon, boundingbox, display_name.

### get_hotel_details

Get full OSM tags for a hotel.

**Parameters:**
- `osm_id` (string, required)
- `osm_type` (string, required) — "node", "way", or "relation"

**Returns:** All OSM tags for the hotel.
