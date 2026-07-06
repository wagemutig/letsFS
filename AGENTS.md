# AGENTS.md — letsFS

## Project: Hotel search for AI agents

letsFS is an MCP server + Python SDK for hotel search. It is the hotel counterpart to [LetsFG](https://github.com/LetsFG/LetsFG) (flights).

## Architecture

- **MCP Server** (`sdk/mcp/src/index.ts`): Stdio JSON-RPC server implementing the MCP protocol. Uses only Node.js built-ins (readline, fetch). No runtime npm dependencies.
- **Python SDK** (`sdk/python/letsfs/`): Client library using urllib (stdlib). No required dependencies.
- **Data Sources**: OpenStreetMap (Nominatim for geocoding, Overpass for hotel discovery) — free, no key. Amadeus for optional live pricing.

## MCP Tools

1. `search_hotels(location, checkin?, checkout?, adults=1, rooms=1, limit=20, currency="EUR")` → hotel list
2. `resolve_location(query)` → lat/lon/boundingbox
3. `get_hotel_details(osm_id, osm_type)` → full OSM tags
4. `load_resources()` → hotel search guide

## Build

```bash
# MCP server
cd sdk/mcp && npm install && npm run build

# Python SDK
cd sdk/python && pip install -e .
```

## Test

```bash
# MCP server — send JSON-RPC over stdio
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | node sdk/mcp/dist/index.js

# Python SDK
cd sdk/python && python -m letsfs search "Berlin" --limit 5
```

## Conventions

- No runtime npm dependencies for the MCP server (Node built-ins only)
- No required Python dependencies (urllib, not requests)
- All HTTP requests include `User-Agent: letsfs-*/0.1.0`
- Nominatim requires a User-Agent header and 1s polite delay between calls
- Amadeus is optional — code must work without it (OSM-only mode)
- VERSION = '0.1.0'
- Server name: 'letsfs'
