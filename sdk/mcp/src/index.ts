#!/usr/bin/env node
/**
 * letsFS MCP Server — Model Context Protocol integration for hotel search.
 *
 * Two pluggable data sources:
 *  1. Overpass API (OpenStreetMap) — DEFAULT, free, no API key.
 *     Geocoding via Nominatim, hotel discovery via Overpass.
 *     Returns hotel name, stars, address, phone, website, email, rooms,
 *     lat/lon, osm_id/osm_type. Does NOT include real-time pricing/availability.
 *  2. Amadeus Hotel Search — OPTIONAL. When LETSFS_AMADEUS_KEY +
 *     LETSFS_AMADEUS_SECRET env vars are set AND checkin/checkout dates are
 *     supplied, letsFS also fetches live pricing & availability from Amadeus.
 *     Amadeus pricing needs an IATA city code (e.g. PAR, LON, NYC) as the
 *     `location`; a plain city name will not match Amadeus.
 *
 * Uses only Node.js built-ins (readline, global fetch, process). No runtime
 * npm dependencies.
 *
 * Usage in Claude Desktop / Cursor config:
 * {
 *   "mcpServers": {
 *     "letsfs": {
 *       "command": "npx",
 *       "args": ["-y", "letsfs-mcp"],
 *       "env": {
 *         "LETSFS_AMADEUS_KEY": "...",
 *         "LETSFS_AMADEUS_SECRET": "..."
 *       }
 *     }
 *   }
 * }
 */

import * as readline from 'readline';

// ── Config ──────────────────────────────────────────────────────────────

const VERSION = '0.1.0';
const UA = `letsfs-mcp/${VERSION}`;

const NOMINATIM_URL = (process.env.LETSFS_NOMINATIM_URL || 'https://nominatim.openstreetmap.org').replace(/\/$/, '');
const OVERPASS_URL = process.env.LETSFS_OVERPASS_URL || 'https://overpass-api.de/api/interpreter';

const AMADEUS_KEY = process.env.LETSFS_AMADEUS_KEY || '';
const AMADEUS_SECRET = process.env.LETSFS_AMADEUS_SECRET || '';
// Single base URL for all Amadeus calls (OAuth, hotel-by-city, hotel-offers).
// Defaults to the test environment, which matches the spec's hotel-offers URL.
const AMADEUS_BASE = (process.env.LETSFS_AMADEUS_BASE || 'https://test.api.amadeus.com').replace(/\/$/, '');
const amadeusEnabled = Boolean(AMADEUS_KEY && AMADEUS_SECRET);

const OVERPASS_TIMEOUT_S = 25;
const OVERPASS_FETCH_CAP = 200;   // cap elements fetched from Overpass per query
const NOMINATIM_RATE_MS = 1000;   // polite delay between Nominatim calls

let lastNominatimCall = 0;

// ── Helpers ─────────────────────────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}

async function rateLimitedNominatim(): Promise<void> {
  const elapsed = Date.now() - lastNominatimCall;
  if (elapsed < NOMINATIM_RATE_MS) await sleep(NOMINATIM_RATE_MS - elapsed);
  lastNominatimCall = Date.now();
}

// ── Nominatim geocoding ─────────────────────────────────────────────────

interface GeoResult {
  lat: string;
  lon: string;
  // Nominatim boundingbox: [south, north, west, east]
  boundingbox: [string, string, string, string];
  display_name: string;
}

async function resolveLocation(query: string): Promise<GeoResult | { error: string }> {
  await rateLimitedNominatim();
  const url = `${NOMINATIM_URL}/search?q=${encodeURIComponent(query)}&format=json&limit=1`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      headers: { 'User-Agent': UA, 'Accept': 'application/json' },
    });
  } catch (e) {
    return { error: `Nominatim request failed: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!resp.ok) {
    return { error: `Nominatim returned HTTP ${resp.status}` };
  }
  const data = await resp.json() as GeoResult[];
  if (!Array.isArray(data) || data.length === 0) {
    return { error: `No geocoding result for location: "${query}"` };
  }
  return data[0];
}

// Convert Nominatim boundingbox [south, north, west, east] → Overpass bbox
// string "south,west,north,east".
function bboxToOverpass(bb: [string, string, string, string]): string {
  const [south, north, west, east] = bb;
  return `${south},${west},${north},${east}`;
}

// ── Overpass (OSM) ──────────────────────────────────────────────────────

interface OverpassElement {
  type: 'node' | 'way' | 'relation';
  id: number;
  lat?: number;
  lon?: number;
  center?: { lat: number; lon: number };
  tags?: Record<string, string>;
}

async function runOverpass(query: string): Promise<OverpassElement[]> {
  const body = `data=${encodeURIComponent(query)}`;
  const resp = await fetch(OVERPASS_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': UA,
      'Accept': 'application/json',
    },
    body,
  });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '');
    throw new Error(`Overpass returned HTTP ${resp.status}: ${detail.slice(0, 200)}`);
  }
  const data = await resp.json() as { elements?: OverpassElement[] };
  return data.elements || [];
}

// Build the hotel-discovery Overpass query for a bounding box.
function hotelsByBboxQuery(bbox: string, cap: number): string {
  return (
    `[out:json][timeout:${OVERPASS_TIMEOUT_S}];\n` +
    `(\n` +
    `  node["tourism"="hotel"](${bbox});\n` +
    `  way["tourism"="hotel"](${bbox});\n` +
    `  relation["tourism"="hotel"](${bbox});\n` +
    `);\n` +
    `out center tags ${cap};\n`
  );
}

// Overpass query for a single element by OSM id + type.
function elementByIdQuery(osmType: string, osmId: string): string {
  const t = osmType.toLowerCase();
  if (t !== 'node' && t !== 'way' && t !== 'relation') {
    throw new Error(`Invalid osm_type "${osmType}" — must be node, way, or relation.`);
  }
  const id = String(osmId).trim();
  if (!/^\d+$/.test(id)) {
    throw new Error(`Invalid osm_id "${osmId}" — must be numeric.`);
  }
  return (
    `[out:json][timeout:${OVERPASS_TIMEOUT_S}];\n` +
    `${t}(${id});\n` +
    `out center tags;\n`
  );
}

// Normalized hotel record returned to MCP clients.
interface HotelRecord {
  osm_id: string;
  osm_type: string;
  name: string;
  stars: string | null;
  address: string;
  city: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  rooms: string | null;
  lat: number | null;
  lon: number | null;
  tags: Record<string, string>;
  price: null;
  pricing_source: 'osm_only';
}

function shapeHotel(el: OverpassElement): HotelRecord {
  const tags = el.tags || {};
  const lat = el.lat ?? el.center?.lat ?? null;
  const lon = el.lon ?? el.center?.lon ?? null;
  const housenumber = tags['addr:housenumber'] || null;
  const street = tags['addr:street'] || null;
  const addrParts = [housenumber, street].filter(Boolean);
  const address = addrParts.length
    ? addrParts.join(' ').trim()
    : (tags['addr:full'] || '');
  return {
    osm_id: String(el.id),
    osm_type: el.type,
    name: tags.name || tags['name:en'] || '(unnamed hotel)',
    stars: tags.stars || null,
    address,
    city: tags['addr:city'] || null,
    phone: tags.phone || tags['contact:phone'] || null,
    email: tags['contact:email'] || tags.email || null,
    website: tags.website || tags['contact:website'] || tags.url || null,
    rooms: tags.rooms || null,
    lat,
    lon,
    tags,
    price: null,
    pricing_source: 'osm_only',
  };
}

// ── Amadeus (optional pricing) ──────────────────────────────────────────

type AmadeusResult =
  | { ok: true; data: unknown }
  | { ok: false; error: string; detail?: unknown };

// Cached OAuth token.
let amadeusToken: { token: string; expiresAt: number } | null = null;

async function getAmadeusToken(): Promise<{ ok: true; token: string } | { ok: false; error: string }> {
  if (amadeusToken && Date.now() < amadeusToken.expiresAt) {
    return { ok: true, token: amadeusToken.token };
  }
  const body =
    `grant_type=client_credentials` +
    `&client_id=${encodeURIComponent(AMADEUS_KEY)}` +
    `&client_secret=${encodeURIComponent(AMADEUS_SECRET)}`;
  let resp: Response;
  try {
    resp = await fetch(`${AMADEUS_BASE}/v1/security/oauth2/token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': UA,
      },
      body,
    });
  } catch (e) {
    amadeusToken = null;
    return { ok: false, error: `Amadeus OAuth request failed: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!resp.ok) {
    amadeusToken = null;
    const detail = await resp.text().catch(() => '');
    return { ok: false, error: `Amadeus OAuth HTTP ${resp.status}: ${detail.slice(0, 200)}` };
  }
  const data = await resp.json() as { access_token?: string; expires_in?: number };
  if (!data.access_token) {
    amadeusToken = null;
    return { ok: false, error: 'Amadeus OAuth response missing access_token.' };
  }
  const expiresIn = data.expires_in ?? 1800;
  amadeusToken = {
    token: data.access_token,
    // refresh 60s before expiry
    expiresAt: Date.now() + (expiresIn - 60) * 1000,
  };
  return { ok: true, token: amadeusToken.token };
}

async function amadeusGet(path: string): Promise<AmadeusResult> {
  const tokenRes = await getAmadeusToken();
  if (!tokenRes.ok) return { ok: false, error: tokenRes.error };
  let resp: Response;
  try {
    resp = await fetch(`${AMADEUS_BASE}${path}`, {
      headers: {
        'Authorization': `Bearer ${tokenRes.token}`,
        'User-Agent': UA,
        'Accept': 'application/vnd.amadeus+json',
      },
    });
  } catch (e) {
    return { ok: false, error: `Amadeus request failed: ${e instanceof Error ? e.message : String(e)}` };
  }
  const text = await resp.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!resp.ok) {
    return { ok: false, error: `Amadeus HTTP ${resp.status}`, detail: data };
  }
  return { ok: true, data };
}

interface AmadeusOffer {
  hotel_id: string;
  hotel_name: string;
  chain_code: string | null;
  price_total: string | null;
  currency: string | null;
  room_type: string | null;
  check_in: string;
  check_out: string;
}

interface AmadeusOffersResult {
  offers: AmadeusOffer[];
  error: string | null;
}

// Fetch live Amadeus hotel offers for a city + dates. `cityCode` is attempted
// verbatim (uppercased) as an IATA city code. If Amadeus rejects it (e.g. the
// caller passed a plain city name), pricing is skipped with an explanatory
// error rather than failing the whole search.
async function fetchAmadeusOffers(
  cityCode: string,
  checkIn: string,
  checkOut: string,
  adults: number,
  rooms: number,
  currency: string,
  limit: number,
): Promise<AmadeusOffersResult> {
  const code = cityCode.trim().toUpperCase();

  // 1) Hotel list by city.
  const listRes = await amadeusGet(
    `/v1/reference-data/locations/hotels/by-city?cityCode=${encodeURIComponent(code)}`
  );
  if (!listRes.ok) {
    return { offers: [], error: `Amadeus hotel list: ${listRes.error}` };
  }
  const listData = listRes.data as {
    data?: Array<{ hotelId?: string; name?: string; chainCode?: string }>;
  };
  const hotelIds = (listData.data || [])
    .map(h => h.hotelId)
    .filter((x): x is string => Boolean(x));
  if (hotelIds.length === 0) {
    return {
      offers: [],
      error: `Amadeus returned no hotels for city code "${code}". Pass an IATA city code (e.g. PAR, LON, NYC) as the location for pricing.`,
    };
  }

  // 2) Hotel offers (v3). Cap the ID batch to keep the request reasonable.
  const idBatch = hotelIds.slice(0, Math.min(Math.max(limit, 1), 100));
  const offersPath =
    `/v3/shopping/hotel-offers?hotelIds=${encodeURIComponent(idBatch.join(','))}` +
    `&checkInDate=${encodeURIComponent(checkIn)}` +
    `&checkOutDate=${encodeURIComponent(checkOut)}` +
    `&adults=${adults}` +
    `&roomQuantity=${rooms}` +
    `&currency=${encodeURIComponent(currency)}`;
  const offRes = await amadeusGet(offersPath);
  if (!offRes.ok) {
    return { offers: [], error: `Amadeus hotel offers: ${offRes.error}` };
  }
  const offData = offRes.data as {
    data?: Array<{
      hotel?: { hotelId?: string; name?: string; chainCode?: string };
      offers?: Array<{
        id?: string;
        checkInDate?: string;
        checkOutDate?: string;
        room?: { typeEstimated?: { category?: string } };
        price?: { currency?: string; total?: string };
      }>;
    }>;
  };

  const offers: AmadeusOffer[] = [];
  for (const entry of (offData.data || [])) {
    const hotel = entry.hotel || {};
    for (const o of (entry.offers || [])) {
      offers.push({
        hotel_id: hotel.hotelId || '',
        hotel_name: hotel.name || '',
        chain_code: hotel.chainCode || null,
        price_total: o.price?.total || null,
        currency: o.price?.currency || null,
        room_type: o.room?.typeEstimated?.category || null,
        check_in: o.checkInDate || checkIn,
        check_out: o.checkOutDate || checkOut,
      });
      if (offers.length >= limit) break;
    }
    if (offers.length >= limit) break;
  }
  return { offers, error: null };
}

// ── Resources ───────────────────────────────────────────────────────────

const GUIDE_TEXT =
  '# letsFS — Hotel Search Guide\n' +
  '\n' +
  '## How It Works\n' +
  'letsFS finds hotels via two complementary data sources:\n' +
  '\n' +
  '1. **OpenStreetMap (Overpass)** — DEFAULT, free, no API key. Gives hotel **discovery**: name, star rating, address, phone, website, email, room count, and lat/lon. Works worldwide. Does NOT include real-time pricing or availability.\n' +
  '2. **Amadeus Hotel Search** — OPTIONAL. When `LETSFS_AMADEUS_KEY` + `LETSFS_AMADEUS_SECRET` env vars are set AND you supply `checkin`/`checkout` dates, letsFS also fetches live pricing and availability. Amadeus pricing requires an **IATA city code** (e.g. `PAR`, `LON`, `NYC`, `BCN`); a plain city name like "Paris" will not match Amadeus.\n' +
  '\n' +
  '## Tools\n' +
  '- **resolve_location** — Geocode a city/place name to lat/lon + bounding box (Nominatim). Always safe to call; read-only.\n' +
  '- **search_hotels** — Main entry point. Pass a `location` (city name for OSM discovery, or IATA city code if you also want Amadeus pricing). Returns hotels with name, stars, address, contact info, lat/lon, osm_id/osm_type. When Amadeus is configured and dates are provided, a separate `amadeus_offers` array is included with live prices.\n' +
  '- **get_hotel_details** — Fetch all OSM tags for a single hotel by `osm_id` + `osm_type` (from search results). Use this for the full raw tag set (e.g. amenities, operator, internet access).\n' +
  '- **load_resources** — Returns this guide (for MCP clients that do not support `resources/read`).\n' +
  '\n' +
  '## Pricing Note\n' +
  'OSM hotel records do not carry prices — the `price` field on each hotel is `null` with `pricing_source: "osm_only"`. Amadeus offers appear in a separate `amadeus_offers` array; correlate them to OSM hotels by **hotel name** (best-effort, not guaranteed — the two systems use different hotel IDs).\n' +
  '\n' +
  '## Critical Rules\n' +
  '- **Discovery is always free.** No key needed for OSM hotel search.\n' +
  '- **Pricing requires Amadeus.** Set `LETSFS_AMADEUS_KEY` + `LETSFS_AMADEUS_SECRET` AND pass `checkin`/`checkout` (YYYY-MM-DD) AND use an IATA city code as the location.\n' +
  '- **Rate limits.** Nominatim requests include a 1-second polite delay and require a `User-Agent` header.\n' +
  '- **OSM data quality varies.** Some hotels have sparse tags (missing phone/website/stars). Use `get_hotel_details` for the complete tag set.\n' +
  '- **osm_id + osm_type together** uniquely identify a hotel. Always pass both to `get_hotel_details`.\n' +
  '\n' +
  '## Environment Variables\n' +
  '- `LETSFS_AMADEUS_KEY` — Amadeus API key (optional, enables pricing)\n' +
  '- `LETSFS_AMADEUS_SECRET` — Amadeus API secret (optional)\n' +
  '- `LETSFS_AMADEUS_BASE` — Amadeus base URL (default `https://test.api.amadeus.com`)\n' +
  '- `LETSFS_OVERPASS_URL` — Override Overpass API URL\n' +
  '- `LETSFS_NOMINATIM_URL` — Override Nominatim base URL\n';

const RESOURCES = [
  {
    uri: 'letsfs://guide',
    name: 'letsFS Hotel Search Guide',
    description:
      'Workflow guide: data sources (OSM + Amadeus), tools, pricing rules, environment variables. ' +
      'Read this before using the hotel tools.',
    mimeType: 'text/markdown',
  },
];

// ── Tool Definitions ────────────────────────────────────────────────────

const TOOLS = [
  {
    name: 'search_hotels',
    description:
      'Search for hotels by city or location — FREE, read-only.\n\n' +
      'Returns hotels from OpenStreetMap (name, stars, address, phone, website, email, rooms, lat/lon, osm_id, osm_type). ' +
      'Works worldwide without any API key.\n\n' +
      'When `LETSFS_AMADEUS_KEY` + `LETSFS_AMADEUS_SECRET` are set AND `checkin`/`checkout` dates are provided, a separate ' +
      '`amadeus_offers` array with live prices is included. Amadeus pricing needs an **IATA city code** (e.g. PAR, LON, NYC) ' +
      'as the `location` — a plain city name will not match Amadeus.\n\n' +
      'See the letsfs://guide resource for the full workflow.',
    inputSchema: {
      type: 'object',
      required: ['location'],
      properties: {
        location: {
          type: 'string',
          description:
            "City name (e.g. 'Paris') for OSM discovery, or IATA city code (e.g. 'PAR') if you also want Amadeus pricing.",
        },
        checkin: {
          type: 'string',
          description: 'Check-in date YYYY-MM-DD (required for Amadeus pricing; ignored by OSM discovery).',
        },
        checkout: {
          type: 'string',
          description: 'Check-out date YYYY-MM-DD (required for Amadeus pricing; ignored by OSM discovery).',
        },
        adults: { type: 'integer', description: 'Number of adults (default: 1)', default: 1 },
        rooms: { type: 'integer', description: 'Number of rooms (default: 1)', default: 1 },
        limit: { type: 'integer', description: 'Max hotels to return (default: 20)', default: 20 },
        currency: {
          type: 'string',
          description: 'Currency code for Amadeus pricing (EUR, USD, GBP). Default: EUR.',
          default: 'EUR',
        },
      },
    },
  },
  {
    name: 'resolve_location',
    description:
      'Geocode a city or place name to lat/lon + bounding box (Nominatim/OpenStreetMap). ' +
      'Always call before search_hotels if you need the resolved coordinates. Read-only, safe to call multiple times.',
    inputSchema: {
      type: 'object',
      required: ['query'],
      properties: {
        query: { type: 'string', description: "City or place name (e.g. 'Berlin', 'New York')" },
      },
    },
  },
  {
    name: 'get_hotel_details',
    description:
      'Get the complete OSM tag set for a single hotel by OSM ID + type. ' +
      'Use this for raw tags not summarized in search results (e.g. amenities, operator, internet access, wheelchair access). ' +
      'Pass the `osm_id` and `osm_type` returned by search_hotels.',
    inputSchema: {
      type: 'object',
      required: ['osm_id', 'osm_type'],
      properties: {
        osm_id: { type: 'string', description: 'OSM element ID (numeric, from search results).' },
        osm_type: {
          type: 'string',
          description: 'OSM element type: node, way, or relation.',
          enum: ['node', 'way', 'relation'],
        },
      },
    },
  },
  {
    name: 'load_resources',
    description:
      'Load the letsFS hotel search guide (data sources, tools, pricing rules, environment variables). ' +
      'Call ONCE at the start of a conversation to understand how to use the hotel tools correctly. ' +
      'Clients that support MCP resources get this automatically — this tool is for clients that do not.',
    inputSchema: { type: 'object', properties: {} },
  },
];

// ── Tool Handlers ───────────────────────────────────────────────────────

async function callTool(name: string, args: Record<string, unknown>): Promise<string> {
  switch (name) {
    case 'search_hotels': {
      const location = String(args.location || '').trim();
      if (!location) return JSON.stringify({ error: 'Parameter "location" is required.' }, null, 2);
      const checkin = args.checkin ? String(args.checkin) : '';
      const checkout = args.checkout ? String(args.checkout) : '';
      const adults = Number(args.adults ?? 1);
      const rooms = Number(args.rooms ?? 1);
      const limit = Math.max(1, Number(args.limit ?? 20));
      const currency = String(args.currency || 'EUR');

      // 1) Geocode via Nominatim.
      const geo = await resolveLocation(location);
      if ('error' in geo) {
        return JSON.stringify({ error: geo.error, location }, null, 2);
      }
      const bbox = bboxToOverpass(geo.boundingbox);

      // 2) Overpass hotel discovery.
      let elements: OverpassElement[];
      try {
        elements = await runOverpass(hotelsByBboxQuery(bbox, OVERPASS_FETCH_CAP));
      } catch (e) {
        return JSON.stringify(
          { error: `Overpass query failed: ${e instanceof Error ? e.message : String(e)}`, location, bbox },
          null, 2,
        );
      }
      const allHotels = elements
        .map(shapeHotel)
        .filter(h => h.name && h.name !== '(unnamed hotel)');
      const hotels = allHotels.slice(0, limit);

      const result: Record<string, unknown> = {
        location,
        resolved: {
          display_name: geo.display_name,
          lat: geo.lat,
          lon: geo.lon,
          boundingbox: geo.boundingbox,
        },
        total_found: allHotels.length,
        returned: hotels.length,
        hotels,
        pricing_source: 'openstreetmap',
        pricing_note: amadeusEnabled
          ? 'OSM discovery does not include prices. See amadeus_offers for live pricing (if available).'
          : 'OSM discovery does not include prices. Set LETSFS_AMADEUS_KEY + LETSFS_AMADEUS_SECRET and provide checkin/checkout dates for live Amadeus pricing.',
      };

      // 3) Optional Amadeus pricing enrichment.
      if (amadeusEnabled && checkin && checkout) {
        const amRes = await fetchAmadeusOffers(location, checkin, checkout, adults, rooms, currency, limit);
        result.amadeus_offers = amRes.offers;
        result.amadeus_error = amRes.error;
      } else if (amadeusEnabled && (!checkin || !checkout)) {
        result.amadeus_offers = [];
        result.amadeus_error =
          'Amadeus configured but checkin/checkout dates not provided — pricing skipped. ' +
          'Pass both checkin and checkout (YYYY-MM-DD) for live prices.';
      } else if (!amadeusEnabled) {
        result.amadeus_offers = null;
      }

      return JSON.stringify(result, null, 2);
    }

    case 'resolve_location': {
      const query = String(args.query || '').trim();
      if (!query) return JSON.stringify({ error: 'Parameter "query" is required.' }, null, 2);
      const geo = await resolveLocation(query);
      if ('error' in geo) return JSON.stringify({ error: geo.error, query }, null, 2);
      return JSON.stringify(
        {
          query,
          display_name: geo.display_name,
          lat: geo.lat,
          lon: geo.lon,
          boundingbox: geo.boundingbox,
        },
        null, 2,
      );
    }

    case 'get_hotel_details': {
      const osmId = String(args.osm_id || '').trim();
      const osmType = String(args.osm_type || '').trim();
      if (!osmId) return JSON.stringify({ error: 'Parameter "osm_id" is required.' }, null, 2);
      if (!osmType) return JSON.stringify({ error: 'Parameter "osm_type" is required (node/way/relation).' }, null, 2);

      let query: string;
      try {
        query = elementByIdQuery(osmType, osmId);
      } catch (e) {
        return JSON.stringify({ error: e instanceof Error ? e.message : String(e) }, null, 2);
      }

      let elements: OverpassElement[];
      try {
        elements = await runOverpass(query);
      } catch (e) {
        return JSON.stringify(
          { error: `Overpass query failed: ${e instanceof Error ? e.message : String(e)}` },
          null, 2,
        );
      }
      if (elements.length === 0) {
        return JSON.stringify(
          { error: `No OSM element found for osm_type=${osmType} osm_id=${osmId}` },
          null, 2,
        );
      }
      const el = elements[0];
      const tags = el.tags || {};
      return JSON.stringify(
        {
          osm_id: String(el.id),
          osm_type: el.type,
          lat: el.lat ?? el.center?.lat ?? null,
          lon: el.lon ?? el.center?.lon ?? null,
          name: tags.name || tags['name:en'] || null,
          tags,
        },
        null, 2,
      );
    }

    case 'load_resources': {
      return GUIDE_TEXT;
    }

    default:
      return JSON.stringify({ error: `Unknown tool: ${name}` });
  }
}

// ── MCP Protocol (stdio JSON-RPC) ──────────────────────────────────────

function send(msg: Record<string, unknown>) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on('line', async (line) => {
  let msg: Record<string, unknown>;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }

  const method = msg.method as string;
  const id = msg.id;

  switch (method) {
    case 'initialize':
      send({
        jsonrpc: '2.0',
        id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {}, resources: {} },
          serverInfo: { name: 'letsfs', version: VERSION },
        },
      });
      break;

    case 'notifications/initialized':
      break;

    case 'resources/list':
      send({ jsonrpc: '2.0', id, result: { resources: RESOURCES } });
      break;

    case 'resources/read': {
      const rParams = msg.params as Record<string, unknown>;
      const uri = rParams.uri as string;
      if (uri === 'letsfs://guide') {
        send({
          jsonrpc: '2.0',
          id,
          result: { contents: [{ uri, mimeType: 'text/markdown', text: GUIDE_TEXT }] },
        });
      } else {
        send({ jsonrpc: '2.0', id, error: { code: -32602, message: `Unknown resource: ${uri}` } });
      }
      break;
    }

    case 'tools/list':
      send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
      break;

    case 'tools/call': {
      const params = msg.params as Record<string, unknown>;
      const toolName = params.name as string;
      const toolArgs = (params.arguments || {}) as Record<string, unknown>;

      try {
        const text = await callTool(toolName, toolArgs);
        send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }] } });
      } catch (e) {
        send({
          jsonrpc: '2.0',
          id,
          result: { content: [{ type: 'text', text: `Error: ${e}` }], isError: true },
        });
      }
      break;
    }

    case 'ping':
      send({ jsonrpc: '2.0', id, result: {} });
      break;

    default:
      if (id) {
        send({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
      }
  }
});

const mode = amadeusEnabled
  ? `Amadeus pricing ENABLED (${AMADEUS_BASE})`
  : 'OSM discovery only (no Amadeus pricing)';
process.stderr.write(`letsFS MCP v${VERSION} | ${mode}\n`);
