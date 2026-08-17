# Business Directory Scraper API

Lightweight FastAPI service that scrapes business **names**, **phone numbers** and
**addresses** for an arbitrary `query` + `location` using `requests` + `BeautifulSoup`.
No API keys required. Ready to deploy on Render.

> **Honest technical note:** Google Maps now renders search results entirely via
> JavaScript, so plain `requests` (no browser) can no longer see the listings
> Google serves. This project therefore scrapes **public web/OSM data** for the
> actual listings, and ships a best-effort Google Maps parser that captures
> server-rendered place data when Google emits any (usually none on the JS app).
> See "Sources" below.

## Quick start (local)

For the **RapidAPI listing** (metadata, endpoints, pricing tiers, step-by-step
publish flow): see [`RAPIDAPI_LISTING.md`](RAPIDAPI_LISTING.md).

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Then call:

```text
GET http://127.0.0.1:8000/scrape?query=restaurant&location=New York
```

Example response (truncated):

```json
{
  "query": "restaurant",
  "location": "New York",
  "count": 1,
  "results": [
    {
      "name": "Grand Central Oyster Bar and Restaurant",
      "phone": "2124906650",
      "address": "East 42nd Street 89, Midtown, Manhattan, New York, 10168",
      "website": "https://www.oysterbarny.com/",
      "latitude": 40.7524,
      "longitude": -73.9773,
      "source": "photon",
      "extra": { "phone_via": "website" }
    }
  ],
  "sources": {
    "openstreetmap": { "status": "ok" },
    "photon": { "status": "ok" }
  }
}
```

## API

| Parameter    | Type    | Default                     | Description                                                        |
|--------------|---------|-----------------------------|--------------------------------------------------------------------|
| `query`      | str     | required                    | Business type or keyword, e.g. `RealEstate`, `restaurant`, `hotel` |
| `location`   | str     | —                           | City / area, e.g. `New York`, `Berlin`. Optional.                    |
| `limit`      | int     | `20`                        | Max results (`1..{max}`; cap configurable via `MAX_RESULTS`). |
| `sources`    | str     | `openstreetmap,photon`      | Comma list: `openstreetmap`, `photon`, `google_maps`, `auto`. |
| `phone_only` | bool    | `false`                     | Return only records that have a phone number.                |
| `enrich`     | bool    | `true`                      | Pull phone numbers + business emails from the business's own website (free). |

Other endpoints:
- `/` (usage)
- `/health` (liveness) — add `?probe=1` to run a real mini-scrape against the
  upstream sources and report each one's status (all sources `ok`/`empty`/`error`).
  Also reports `database` status when Supabase is configured.
- `/export.csv` — same query params as `/scrape`, but returns a CSV download
  (`Content-Disposition: attachment`). Results are cached per query+location.
  Great for lead-list apps and the automated lead packs.
- `/categories` — list of all 81 supported business niches (name + keyword pattern)
- `/leads?query=&location=&limit=` — read collected leads from the Supabase
  database (only populated once `DATABASE_URL` is configured). **Protected**: send
  the `LEADS_API_KEY` secret as an `X-API-Key` header. If `LEADS_API_KEY` is unset
  the endpoint is disabled (403) rather than open.
- `/docs` (Swagger UI)

## Optional Supabase persistence

Set the `DATABASE_URL` env var (e.g. Supabase session-pooler string) and the app
gains durable storage on top of the in-memory cache:

| What | Benefit |
|------|---------|
| `scrape_cache` table | Cold-start timeouts vanish — a cached scrape survives instance restarts, shared across all serverless instances |
| `leads` table | Every scraped business is stored (deduped per query+name+address) — build lead packs or a queryable lead DB |
| `/leads` + `/health` database status | Read back collected leads; verify DB health |

Without `DATABASE_URL` everything degrades gracefully to the in-memory cache — no
crash, no setup required. Pooler format:

```
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-<N>-<region>.pooler.supabase.com:5432/postgres
```

## Enrichment fields

`enrich=true` (default) visits each business's website and extracts:
- **`phone`** — from `tel:` links, `itemprop="telephone"`, JSON-LD, and visible text
- **`email`** (in `extra.email`) — from `mailto:` links, `itemprop="email"` /
  meta tags, JSON-LD, and visible text (max 3). Only *published* business
  emails are returned — the app never fabricates or guesses addresses.

## Self-hosting knobs

| Env var           | Default | Effect                                        |
|-------------------|---------|-----------------------------------------------|
| `MAX_RESULTS`     | `50`    | Cap on `limit` per request (raise for bigger export packs) |
| `OVERPASS_RETRIES`/`OVERPASS_DEADLINE` | `1`/`25` | Overpass mirror retries & turnaround |
| `RATE_LIMIT_PER_IP` | `30`  | Requests per IP per minute                     |
| `ENRICH_MAX_SITES` | `10`   | Sites visited per scrape for phone/email lookup |

## Sources

- **openstreetmap** — geocodes the location (Nominatim), then queries Overpass for
  businesses by OSM tag (e.g. `office=estate_agent`, `amenity=restaurant`).
  Returns `name`, `address`, `phone`, `website` when those tags exist in OSM.
  This is the only free source that yields real phone numbers.
  Public Overpass mirrors can be rate-limited/busy; the app retries several mirrors
  and degrades gracefully (you'll see `"status": "error"` per source, never a crash).
- **photon** — public Photon (komoot) OSM POI search. Reliable, fast, keyless.
  Good `name` + `address`, no phone field. Results are distance-sorted to the location.
- **google_maps** — best-effort parser of the Google Maps HTML
  (`schema.org` microdata + `APP_INITIALIZATION_STATE`). Usually returns nothing
  because results are JS-rendered; included for completeness when you set
  `sources=google_maps`. Scraping Google Maps violates its ToS — use with caution.

### Free phone enrichment (default ON)

Since OSM phone tags are sparse, the app tries to pull phone numbers from the
business's **own website** — 100% free, no keys, no card, no ToS issue:

1. A business that has a `website` (from OSM tags) or an OSM id/photon hit is picked.
2. For Photon results the website is resolved via the public OSM API
   (rate-limited to 1 req/s).
3. The site is fetched and a phone is extracted from `tel:` links,
   schema.org `itemprop="telephone"`, JSON-LD, and text patterns.

Pass `enrich=false` to disable. `phones_enriched` in the response counts how many
phones came from this pass, and results carry `extra.phone_via` (`website` vs `osm_tag`).
Coverage grows with OSM `website` tags — most effective for businesses that list a
phone on their site (small/medium businesses, hotels, clinics, workshops...).

### Phone numbers: the honest picture

Phones come from OpenStreetMap tags, which are sparse (10–25 % of mapped
businesses). For dependable phone data in production, pair this app with an
official API (e.g. Google Places / Foursquare) via a small custom source — the
`scraper.py` module is designed to be extended by subclassing `BaseScraper`.

## Configuration (env vars)

| Variable             | Default | Purpose                                    |
|----------------------|---------|--------------------------------------------|
| `SCRAPER_USER_AGENT` | Chrome UA | User-Agent used for all HTTP requests    |
| `SCRAPER_TIMEOUT`    | `20`    | Socket timeout (s) for HTML requests        |
| `OVERPASS_DEADLINE`  | `45`    | Overpass query timeout (s)                  |
| `OVERPASS_RETRIES`   | `1`     | Extra lighter retry passes after failure    |
| `MAX_BBOX_DEG`       | `1.3`   | Cap on geocoded bounding-box size (degrees) |
| `MAX_PHOTON_KM`      | `120`   | Drop Photon hits farther than this (km)     |
| `ENRICH_MAX_SITES`   | `10`    | Max websites fetched per request            |
| `ENRICH_USE_OSM_API` | `1`     | Resolve Photon websites via OSM API (`0/1`) |
| `ENRICH_DEFAULT`     | `1`     | Default for the `enrich` query param        |
| `GEO_CACHE_TTL`      | `3600`  | Cache TTL (s) for Nominatim geocoding        |
| `RATE_LIMIT_PER_IP`  | `30`    | Max requests per IP per window (`0` = off)   |
| `RATE_LIMIT_WINDOW`  | `60`    | Rate-limit window (seconds)                  |
| `DATABASE_URL`       | —       | Supabase/Postgres URL — enables durable cache + leads table |
| `LEADS_API_KEY`      | —       | Secret required to read `/leads` (`X-API-Key` header); unset = disabled |
| `QUALITY_MIN_COUNT`    | `40`    | Lead-pack quality gate: min rows        |
| `QUALITY_MIN_PHONE_PCT`| `15`    | Lead-pack quality gate: min phone %     |
| `QUALITY_MIN_EMAILS`   | `3`     | Lead-pack quality gate: min emails      |

## Deploy on Render

1. Push this folder to a GitHub repo.
2. On Render: **New → Web Service**, pick the repo.
   Language is auto-detected (Python 3.12).
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Deploy, then open `https://<your-service>.onrender.com/scrape?query=RealEstate&location=New%20York`

A `render.yaml` blueprint is included so you can also use **New → Blueprint**.

## Automated lead packs (CSV, free cron)

Sellable, ready-made CSV lead packs are auto-generated **every day at 03:00 UTC**
by a free GitHub Actions cron (no card, no server cost). Each pack is a CSV of
`name, phone, email, address, website, latitude, longitude, source` for a niche +
city, sorted so records with a phone appear first. Packs are committed to
`docs/leads/` so every CSV gets a permanent public URL:

```text
https://raw.githubusercontent.com/h3lllsing/Scraping-script/main/docs/leads/<city>_<query>-<YYYY-MM-DD>.csv
```

- Edit `leadpacks.json` to change which niche × city packs to build. The default
  roster is 18 cities across US/UK/EU/CA/AU/NZ × 58 niche packs (restaurant,
  cafe, hotel, salon, dentist, gym) — chosen because OSM/Photon contact tags are
  far richer there than in South-Asian/Dubai cities. Every pack passes a
  **quality gate** before it is written: at least 40 rows AND (15% phone rate OR
  3+ emails). Packs that fail are skipped and the previous day's CSV is kept, so
  quality stays high even when a data source is flaky.
- Trigger manually: GitHub → **Actions → Lead Packs → Run workflow**.
- Run locally: `python generate_leadpack.py --query restaurant --location New York`
  (or `--all`). Set `LEADPACK_API` to point at any instance of this app. Gate
  thresholds are tunable via `QUALITY_MIN_COUNT`, `QUALITY_MIN_PHONE_PCT`,
  `QUALITY_MIN_EMAILS`.

The workflow calls your live API's `/scrape?enrich=true` endpoint. Because the
enrichment pass is already free, a pack that includes businesses with websites
will contain phones too (`phone_via=website` column).

## Legal

Public OpenStreetMap/Photon data is used per their usage policies (ODbL; Photon
asks for fair usage + attribution). Respect the ToS of any web source you point
this at, and do not hammer shared public endpoints.

Important if you **resell** the output (Gumroad/RapidAPI buyers):
- OSM data is licensed under **ODbL** — any product derived from it must credit
  OpenStreetMap and, when shared publicly, carry the same open license. Every
  generated pack now auto-includes the attribution line
  *"Data © OpenStreetMap contributors (ODbL)"* in its CSV header; also keep it in
  your product listing, and publish the ODbL share-alike terms alongside paid
  packs.
- Emails are only ever ones the businesses themselves published (never guessed).
  Running cold-email campaigns (sending unsolicited bulk mail to the scraped
  addresses) can breach anti-spam law (CAN-SPAM / GDPR / PECR in the EU/UK) and
  kills deliverability. Resell them as research/subscription leads, or get
  recipients' consent before contacting.