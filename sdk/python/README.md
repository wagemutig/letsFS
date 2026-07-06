# letsFS Python SDK

Hotel search for AI agents. **Free, worldwide hotel discovery** via
OpenStreetMap (Nominatim + Overpass), with **optional live pricing** via
Amadeus when credentials are configured.

## Install

```bash
# Core (zero runtime dependencies — uses urllib from the stdlib)
pip install -e .

# With the richer CLI (typer + rich)
pip install -e ".[cli]"
```

## Quick start

```python
from letsfs import LetsFS

ls = LetsFS()                       # OSM-only mode, no API key needed
res = ls.search("Bali", limit=20)
for h in res.hotels:
    print(h.summary())
# Grand Hyatt Bali | ★5 | ...
```

With Amadeus live pricing (pass an **IATA city code** like `PAR`):

```python
ls = LetsFS(amadeus_key="...", amadeus_secret="...")
res = ls.search("PAR", checkin="2026-07-13", checkout="2026-07-20", adults=1)
for offer in res.amadeus_offers or []:
    print(offer.hotel_name, offer.price_total, offer.currency)
```

## CLI

```bash
letsfs search "Bali" --limit 20
letsfs location "Paris"
letsfs hotel 123456 way
letsfs config
letsfs --version
```

`--json` on any subcommand emits machine-readable JSON.

## Data sources

1. **Nominatim** (geocoding) — `GET /search?q=<city>&format=json&limit=1`.
   Requires a `User-Agent` header; letsFS enforces a polite 1-second delay
   between calls.
2. **Overpass API** (hotel discovery) — `POST /api/interpreter` with an
   `[out:json]` query for `tourism=hotel` nodes/ways/relations in the
   Nominatim bounding box. Returns OSM tags: `name`, `stars`, `addr:*`,
   `phone`, `website`, `contact:email`, `rooms`, etc.
3. **Amadeus** (optional pricing) — OAuth2 client-credentials flow, then
   `GET /v3/shopping/hotel-offers`. Needs an **IATA city code** as the
   `location` (a plain city name will not match Amadeus).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `LETSFS_AMADEUS_KEY` | (none) | Amadeus API key (enables live pricing) |
| `LETSFS_AMADEUS_SECRET` | (none) | Amadeus API secret |
| `LETSFS_AMADEUS_BASE` | `https://test.api.amadeus.com` | Amadeus base URL |
| `LETSFS_OVERPASS_URL` | `https://overpass-api.de/api/interpreter` | Overpass API URL |
| `LETSFS_NOMINATIM_URL` | `https://nominatim.openstreetmap.org` | Nominatim base URL |
| `LETSFS_USER_AGENT` | `letsfs-python/0.1.0` | User-Agent header |
| `LETSFS_TIMEOUT` | `30` | HTTP request timeout (seconds) |

A config file at `~/.letsfs/config.json` (or `$LETSFS_CONFIG_DIR/config.json`)
is also read; explicit constructor kwargs win over env, which wins over the
file, which wins over defaults.

## Pricing notes

- **Discovery is always free.** No key needed for OSM hotel search.
- **Pricing requires Amadeus.** Set both `LETSFS_AMADEUS_KEY` and
  `LETSFS_AMADEUS_SECRET` AND pass `checkin`/`checkout` (`YYYY-MM-DD`) AND
  use an IATA city code as the `location`.
- OSM hotel records do not carry prices — the `price` field on each hotel is
  `None` with `pricing_source="osm_only"`. Amadeus offers appear in a
  separate `amadeus_offers` array; letsFS best-effort attaches the cheapest
  matching Amadeus price to OSM hotels by normalized name.
- OSM and Amadeus use **different hotel IDs** — name matching is the only
  available heuristic and is not guaranteed.

## Tests

```bash
# Deterministic, no network
pytest -m "not live"

# Including live network calls against Nominatim/Overpass
pytest
```
