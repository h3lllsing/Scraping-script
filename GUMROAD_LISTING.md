# Gumroad lead-pack store — listing text & setup

Ready-to-paste copy for a Gumroad storefront selling OSM-derived business lead packs.
Packs are generated weekly from the live API; **paid packs are delivered privately
via Gumroad file uploads** — only the free sample is stored publicly.

## Product lineup

| Product | Contents | Price |
|---|---|---|
| Free sample | 1 city x niche pack (50 rows) | $0 (email opt-in) |
| Single pack | 1 city x niche (40-50 rows) | $9 |
| City bundle | 5 niches x 1 city (ZIP) | $29 |
| Niche mega-bundle | 1 niche x ~7 cities (ZIP) | $49 |
| All packs bundle | all current packs (ZIP) | $79 |

After a pack passes the quality gate (30+ rows, phone/email present), upload a
snapshot ZIP to the Gumroad product so buyers get the file instantly (private,
buyer-gated). The free sample links to a stable raw URL (below) that serves the
latest committed snapshot.

## Free sample — stable URL

```text
https://raw.githubusercontent.com/h3lllsing/Scraping-script/main/docs/leads/free-sample/sample-pack.csv
```

This is the only pack stored publicly (Melbourne dentists). **Paid packs are
never committed to the repo** — they are delivered as Gumroad file uploads
(`docs/leads/paid/README.md` explains the flow). Replacing the sample happens
only when you deliberately refresh it.

## Listing copy — single pack (e.g. Houston Dentists)

> ### Houston Dentist Leads (freshly scraped)
> 40-50 dental businesses in Houston with published contact info. Each row:
> business name, phone (when the business publishes one), email (published
> only), street address, website, GPS coordinates.
> - Scraped live from OpenStreetMap + each business's own website
> - Sorted so records with a phone come first
> - Updated daily; same-day fresh data on the live link
> - Data © OpenStreetMap contributors (ODbL) — see licence notes below

## Listing copy — city bundle (e.g. New York)

> ### New York Business Leads — 5 niches (restaurant, cafe, hotel, salon, dentist)
> Five ready-to-use CSV packs for New York: ~250 businesses total with phone,
> email, address, website and GPS. Perfect for local outreach, research, or
> building your own directory.
> - Includes: restaurants, cafes, hotels, salons, dentists
> - Phones & emails are only the ones businesses publish themselves
> - Data © OpenStreetMap contributors (ODbL)

## Listing copy — niche mega-bundle (e.g. US Restaurants)

> ### US Restaurant Leads — 7 cities (New York, LA, Chicago, Miami, Austin, Houston, Dallas)
> ~350 restaurant businesses with published contact info across the biggest US
> markets. ZIP download, one CSV per city.
> - Data © OpenStreetMap contributors (ODbL)

## Honest expectations (put in every listing)

- Phones/emails are **only ones the businesses publish** (OSM tags + the
  business's own website). Never guessed or fabricated.
- Expect roughly 5-15% of rows to have a phone, fewer to have an email,
  depending on niche and city. Packs are **business directories** (name,
  address, website, GPS + published contact data) — ideal for local research,
  directory building, and sales prospecting where the caller uses the listed
  website or main line.
- This is research/outreach data. **Do not** run unsolicited bulk cold-email
  campaigns — it can breach CAN-SPAM / GDPR / PECR and kills deliverability.

## Licence & attribution

- Data derived from OpenStreetMap, licensed under **ODbL** (share-alike).
- Each CSV includes the header line:
  `# Data © OpenStreetMap contributors (ODbL) — https://www.openstreetmap.org/copyright`
- Keep the attribution in the product listing and any redistribution.

## Weekly refresh checklist

1. Generate packs locally: `python generate_leadpack.py --all --base https://<render-service>.onrender.com`
   (output lands in the gitignored `packs/` folder; nothing is committed publicly).
2. Review the summary — keep only packs that pass the quality gate.
3. Zip the packs (single / city bundle / niche mega-bundle / all-packs bundle)
   and upload to the matching Gumroad products.
4. The free sample URL is stable (`docs/leads/free-sample/sample-pack.csv`);
   refresh it only when the sample data changes meaningfully.
5. The daily 03:00 UTC cron still runs as a **canary** (API + quality-gate
   health check) — it no longer publishes packs.