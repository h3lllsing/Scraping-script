# RapidAPI Listing Pack — Business Directory Scraper API

Everything you need to put the API live on RapidAPI. Copy-paste-ready.

> **Live base URL:** `https://scraping-script-xi.vercel.app`
> **Fee reality (2026):** free to list. RapidAPI takes **25%** marketplace fee on
> payments; payouts only via **PayPal** (~2% up to $20). You receive net ~73% of
> list price. List at ~$35/mo → you keep ~$25.

---

## 1. Listing metadata (copy-paste)

| Field | Value |
|---|---|
| **API name** | Business Directory Scraper API |
| **Tagline** | Scrape business name, phone & address data worldwide |
| **Category** | Data → Business Data |
| **Sub-category** | Lead Generation / Business Database |
| **Tags** | scraping, business data, leads, contact data, openstreetmap, directory |
| **Version** | 1.0.0 |
| **Base URL** | `https://scraping-script-xi.vercel.app` |
| **Support/Contact** | DevTools reachable via RapidAPI messages (see docs in repo) |

## 2. Long description (copy-paste)

```
Scrape real business contact data — name, phone, email, address, website,
latitude and longitude — for any query + location worldwide. Built on free public
sources (OpenStreetMap + Photon) so there are no hidden third-party fees.

Perfect for:
- Building lead lists for sales outreach (only emails businesses themselves publish)
- Local business directories & map apps
- Market research dashboards
- Enriching CRM records with verified business details

Key features
- Search 80+ business types: restaurants, real estate agents, hotels, dentists,
  gyms, plumbers, electricians, roofing/HVAC, car dealers, lawyers, insurance,
  clinics, salons, cinemas, marinas and more
- Worldwide coverage — works with any city name (New York, London, Berlin, Sydney…)
- Free phone + email enrichment: set enrich=true (default) and the API visits the
  business's own website to pull a phone number and any published contact email
- phone_only=true returns only records with a phone
- sources=openstreetmap,photon,google_maps lets you control which source is used
- /export.csv downloads the same results as a ready-to-use CSV file

Quick example
GET /scrape?query=restaurant&location=New York&limit=50

Honest data note
Phones come from OpenStreetMap tags (10-25% of mapped businesses) plus website
enrichment. Name + address coverage is strong across all big cities; phone
coverage is partial but real and verified from the business's own website.
Emails are only ever ones the businesses themselves published (never guessed).
```

## 3. Endpoints (define in RapidAPI Provider Dashboard)

| Method | Endpoint | Parameters | Notes |
|---|---|---|---|
| GET | `/scrape` | `query` (req), `location`, `limit` (1–50), `sources`, `phone_only`, `enrich` | Main endpoint (JSON) |
| GET | `/export.csv` | `query` (req), `location`, `limit`, `sources`, `phone_only`, `enrich` | Same data as CSV download |
| GET | `/categories` | — | List of all supported business niches |
| GET | `/` | — | Usage info (nice to expose) |
| GET | `/health` | — | Liveness check |

**Parameter definitions (copy into RapidAPI):**

- `query` — string, **required**. Business type: RealEstate, restaurant, hotel, dentist, gym, plumber, electrician, lawyer, insurance, car repair, salon, clinic, pharmacy, bank, school, hospital…
- `location` — string, optional. City/area name: `New York`, `London`, `Berlin`, `Dubai`. Empty = try worldwide.
- `limit` — integer 1–50, default 20.
- `sources` — comma list: `auto` (default), `openstreetmap`, `photon`, `google_maps`.
- `phone_only` — boolean, default false.
- `enrich` — boolean, default true. Website phone + email enrichment.

## 4. Sample request (cURL — use in examples)

```bash
curl --request GET \
  --url 'https://scraping-script-xi.vercel.app/scrape?query=restaurant&location=New%20York&limit=5&enrich=true' \
  --header 'X-RapidAPI-Key: YOUR_RAPIDAPI_KEY'
```

### Sample response

```json
{
  "query": "restaurant",
  "location": "New York",
  "limit": 5,
  "count": 5,
  "phone_only": false,
  "enrich": true,
  "phones_enriched": 2,
  "generated_at": "2026-08-16T03:00:00Z",
  "results": [
    {
      "name": "Grand Central Oyster Bar and Restaurant",
      "phone": "2124906650",
      "address": "East 42nd Street 89, Midtown, Manhattan, New York, 10168",
      "website": "https://www.oysterbarny.com/",
      "latitude": 40.7524188,
      "longitude": -73.9773429,
      "source": "photon",
      "extra": { "phone_via": "website" }
    }
  ],
  "sources": { "openstreetmap": {"status": "ok"}, "photon": {"status": "ok"} }
}
```

## 5. Pricing plans (recommended — tune to your data costs)

> Each request costs Vercel serverless time + public-source quota. Price so you
> keep ~$15–40/user/month and discourage excessive hammering of shared sources.

| Plan | Price/mo | Requests/mo | Rate limit |
|---|---|---|---|
| **Developer** | $19 | 2,000 | 1 req/s, 25 req/day |
| **Startup** | $49 | 10,000 | 2 req/s, 100 req/day |
| **Business** | $99 | 30,000 | 5 req/s, 500 req/day |

Net to you (after 25% + ~2% PayPal): Developer ~$13.85, Startup ~$35.75,
Business ~$72.20.

Set overage pricing to `off` initially to protect the free upstream sources
(Overpass rate-limits). Re-enable later when revenue is proven.

**Start lean:** Developer + Startup first, add Business when demand appears.

## 6. Step-by-step — make the API live (in browser)

1. Go to **rapidapi.com** → sign in (GitHub/Google OK). If not signed up, register free.
2. Dashboard → **My APIs** → **Add API** → choose **"REST API from scratch"** (or upload ours — simpler to build from scratch).
3. **Endpoint**: Method `GET`, path `/scrape`.
4. **Base URL**: `https://scraping-script-xi.vercel.app`
5. Add parameters exactly as in section 3 (`query` required, others optional) with descriptions + example values.
6. **Metadata**: paste the description from section 2, name, tagline, category, tags.
7. **Pricing**: create the plans from section 5 with rate limits.
8. Header defaults: add `Accept: application/json` and Content-Type — RapidAPI sends its own `X-RapidAPI-Key`/`X-RapidAPI-Host`; no special handling needed server-side.
9. Test with the **Test Endpoint** panel (it will call the live URL).
10. Save → set the project **Public** → **Publish**.

## 7. Payouts (PayPal)

- Dashboard → My APIs → your **Personal Account** → **Payment Settings**.
- Add your **PayPal** account (only payout method).
- Payouts monthly: charges are consolidated, processed end of following month,
  then paid to PayPal (first week of the month after, roughly). Minimum payout
  threshold applies (typically ~$25) — keep tiers above that per month.
- PayPal fee (about 2%, max $20) is deducted from your payout on top of the 25%.

## 8. Launch checklist

- [ ] `/scrape` tested via RapidAPI Test panel (expect ~10–30 s worst case on cold start)
- [ ] Description + tags filled (rankings depend on them)
- [ ] Plans published (Developer + Startup)
- [ ] PayPal added in Payment Settings
- [ ] Set a logo/icon (RapidAPI lets you upload one — improves CTR)
- [ ] Note in description: fair-usage on public OSM sources
- [ ] Compliance: paste the OSM attribution requirement into the listing/tos area
      ("Data © OpenStreetMap contributors, ODbL") and mention emails are only
      those businesses publish themselves.

## 9. Honest caveats (tell customers, avoid refunds)

- Phone coverage is partial (OSM tags + website enrichment). Advertise as
  "business listings with partial phone coverage", not "verified phone database".
- Google Maps source returns little (JS-rendered). Default `openstreetmap,photon`.
- First request after idle can be slow (serverless cold start). Not a functional issue.

## 10. Files referenced by this listing

- App: `app.py` (metadata + docs updated for import). OpenAPI: `https://scraping-script-xi.vercel.app/openapi.json`
- Scraper/sources: `scraper.py`
- Sample data packs (Gumroad cross-sell): `docs/leads/*.csv` via GitHub raw URLs