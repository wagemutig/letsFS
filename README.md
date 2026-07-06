# letsFS

**Lets Fucking Stay** — Hotel search for AI agents. Free, open-source, agent-native.

letsFS gives any MCP-compatible agent (Claude, Cursor, Windsurf, Hermes, etc.) the ability to search for hotels worldwide. Discovery is powered by **OpenStreetMap** (Nominatim + Overpass) — free, no API key required. Optional **Amadeus** integration adds real-time pricing and availability.

## Why?

[LetsFG](https://github.com/LetsFG/LetsFG) does flights. letsFS does hotels. Same spirit: zero-config, zero-browser, zero-markup. Built for autonomous agents.

## Quick Start

### MCP Server (Claude Desktop / Cursor / Hermes)

Add to your MCP client config:

```json
{
  "mcpServers": {
    "letsfs": {
      "command": "npx",
      "args": ["-y", "letsfs-mcp"],
      "env": {
        "LETSFS_AMADEUS_KEY": "your_amadeus_key (optional)",
        "LETSFS_AMADEUS_SECRET": "your_amadeus_secret (optional)"
      }
    }
  }
}
```

Without Amadeus credentials, you get hotel discovery (name, stars, address, phone, website, coordinates) from OpenStreetMap. With Amadeus, you also get real-time room pricing and availability.

### Python SDK

```bash
pip install letsfs
```

```python
from letsfs import LetsFS

ls = LetsFS()

# Free OSM discovery — no API key
hotels = ls.search("Bali", limit=20)
for h in hotels:
    print(f"{h.name} | ★{h.stars or 'N/A'} | {h.address}")

# With Amadeus pricing
ls = LetsFS(amadeus_key="...", amadeus_secret="...")
hotels = ls.search("Bali", checkin="2026-07-13", checkout="2026-07-20", adults=2)
for h in hotels:
    print(f"{h.name} | {h.price} {h.currency} | {h.address}")
```

### CLI

```bash
# Search hotels
letsfs search "Bali" --limit 20

# Geocode a location
letsfs location "Denpasar, Indonesia"

# Get hotel details by OSM ID
letsfs hotel 58467591 node
```

## Architecture

```
letsFS/
├── sdk/
│   ├── mcp/          # MCP Server (TypeScript) — the core deliverable
│   │   └── src/index.ts
│   ├── python/       # Python SDK + CLI
│   │   └── letsfs/
│   │       ├── client.py    # Main client (urllib, no deps)
│   │       ├── cli.py       # CLI (argparse)
│   │       ├── models.py    # Data models (dataclasses)
│   │       └── config.py    # Config from env / ~/.letsfs/config.json
│   └── js/           # JS SDK (planned)
├── skills/           # Agent skill (SKILL.md)
├── docs/             # Documentation
└── models/           # Shared data models
```

### Data Sources

| Source | Free? | API Key? | Provides |
|--------|-------|----------|----------|
| **OpenStreetMap** (Nominatim + Overpass) | ✅ | ❌ | Hotel discovery: name, stars, address, phone, website, coords |
| **Amadeus Hotel Search** | ✅ (sandbox) | ✅ | Real-time pricing, availability, room types |

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_hotels` | Search hotels by city/location. Returns name, stars, address, contact, price (if Amadeus configured) |
| `resolve_location` | Geocode a city name to lat/lon + bounding box |
| `get_hotel_details` | Get full OSM tags for a specific hotel |
| `load_resources` | Load the hotel search guide |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LETSFS_AMADEUS_KEY` | No | Amadeus API key (enables pricing) |
| `LETSFS_AMADEUS_SECRET` | No | Amadeus API secret |
| `LETSFS_AMADEUS_BASE` | No | Amadeus base URL (default: `https://test.api.amadeus.com`) |
| `LETSFS_OVERPASS_URL` | No | Override Overpass API URL |
| `LETSFS_NOMINATIM_URL` | No | Override Nominatim URL |

## License

MIT — see [LICENSE](LICENSE).
