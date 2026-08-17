# Production Audit — Business Directory Scraper API

**Verdict: PASS WITH ISSUES** · Overall score **67/100** · Audited 2026-08-17 · Live target `https://scraping-script-xi.vercel.app`

---

## 1. Project & requirements audit

- **Original objective:** Sellable lead-pack product (niche × city CSV packs) on Gumroad, backed by a keyless business-scraper API; honest, ODbL-compliant data; distribution via GitHub raw URLs + cron refresh.
- **Actual implementation:** FastAPI scraper (OSM/Photon/Google-Maps-best-effort) + Postgres persistence + daily GitHub Actions cron generating quality-gated CSVs into `docs/leads/` + Gumroad/distribution plan.
- **Requirements vs implementation:** Delivered. Roster validated against real data (no Dubai/Asia), quality gate enforced, ODbL attribution embedded.
- **Missing requirements:** Live uptime monitoring; load/performance validation; delivery that protects the paid product (see Critical #2).
- **Scope creep:** Sales tracker CLI, distribution plan, Gumroad copy — useful, minor, in-scope for the goal.

## 2. Repository / file structure audit

- Clean layout: `app.py` (API), `scraper.py` (engine), `db.py` (persistence), `generate_leadpack.py` (product pipeline), `track_sales.py` (ops), `test_scraper.py`, configs, docs, `docs/leads/`.
- **No unused files.** **No dead code** (2 rounds of dead-code removal in history). **No duplicate modules.**
- `vercel.json`, `render.yaml`, `.github/workflows/{tests,leadpacks}.yml`, `.env.example` all present and valid.
- Minor: `.gitignore` line 13 `.env*` is over-broad (would ignore a future `.env.example`-style file).

## 3. Architecture audit

- **Good separation of concerns.** Scraper engine is subclassable (`BaseScraper`), sources are pluggable dicts; app layer is thin; DB layer degrades gracefully to memory.
- Data flow: `query+location → search_all → (OSM|Photon|GM parallel) → dedupe → enrich → payload/cache/DB`.
- Dependencies: only `requests`, `bs4`, `cachetools`, `psycopg2`, FastAPI/uvicorn. Low coupling, easy to extend.
- **Scalability ceiling:** single shared DB connection + global lock serializes DB work; Vercel serverless + Hobby 60s cap (see Performance/Reliability).

## 4. API audit

| Endpoint | Params | Validation | Status |
|---|---|---|---|
| `/scrape` | query, location, limit, sources, phone_only, enrich | ✅ min_length/ge/le, `MAX_RESULTS` clamp | ⚠️ 504s on heavy queries |
| `/export.csv` | same | ✅ | ✅ 200 (cached) |
| `/health` | probe | ✅ | ⚠️ `probe=1` times out live |
| `/categories` | — | ✅ | ✅ 81 niches |
| `/leads` | query, location, limit(≤200) | ✅ API-key gated | ✅ 401 without key, 403 if key unset |
| `/` | — | ✅ | ✅ |

- Response schema consistent (query/location/count/results/sources/phones_enriched/generated_at). Source status reported per-source, no crash on failure.
- **Error handling:** upstream failures → per-source `"error"` status, never 500. But **platform-level 504 (Vercel 60s) bypasses app error handling** — client sees `FUNCTION_INVOCATION_TIMEOUT` with no graceful partial.
- **Security:** `/leads` key-gated (401/403 correctly). No rate-limit on enrichment specifically, but global 30/min per IP applies.
- **Caching:** memory TTL 600s + Postgres-backed; per-key. Good.

## 5. Scraper engine audit

- **OSM/Overpass:** mirror rotation (de/archive → kumi → coffee), retry+light-fallback, bbox cap, tag rules (81 niches). Semicolon bug fixed and verified live (`probe` → ok).
- **Photon:** longseest-match tag map, distance-sort + radius filter, 429/403 surfaced as SourceError. Reliable live.
- **Google Maps:** honest best-effort; JS-rendered so usually empty; **ToS-violating** — caveat documented, but shipping it as a listed source is a compliance smell.
- **Fallbacks:** one source failing never breaks others; unknown sources get error status.
- **Dedup:** (normalized name, normalized address) only → **cross-source duplicates survive** (OSM vs Photon address formats differ). Live sample: 50 rows, 48 unique names.
- **Limits/pagination:** `MAX_RESULTS` clamp; Overpass `limit`; Photon `limit*2` cap 50. Pagination N/A (top-N product).
- **Timeouts/retries:** per-source timeouts set, but **Overpass retry guard `elapsed<20s` almost never fires** because a single HTTP attempt can run 40s — retry path is effectively dead for slow-timeout cases.

## 6. Business-data quality audit

- **Name:** OSM/Photon names present; generic names ("Dentist") common in OSM — genuine, but noisier.
- **Phone:** OSM tags sparse (realistic 5–15%, dentists 16–46%). `_clean_phone` accepts **7-digit numbers** → possible junk from website text (false positives).
- **Address:** reconstructed from OSM parts / Photon fields; good.
- **Website:** from OSM tags or resolved via OSM API (1 req/s). Good.
- **Email enrichment:** low yield (published-only — correct, but packs rarely hit `emails≥2`; gate effectively phone-driven).
- **Missing data / false positives:** restaurants/cafes/hotels/salons packs are directory-style (2–10% phones) — the honest limitation; dentists are the only strong niche.
- **International locations:** US/UK/EU/CA/AU/NZ only — intentional, data-rich choice.

## 7. Website enrichment audit

- Phone: tel: links → itemprop/meta → JSON-LD → body-regex; date-like false-positive guard. Solid.
- Email: mailto → itemprop/meta → JSON-LD → body regex; image/example-domain filters. Solid.
- **Crawl behavior:** 4-hop redirects, 350 KB body cap, 7s per site, 4 workers, `ENRICH_MAX_SITES=6` on prod. Good bounds.
- **Broken sites/redirects/SSL:** swallowed per-business; safe.
- **SSRF:** `_is_safe_url` blocks private/loopback/link-local/reserved/cloud-metadata IPs; redirects re-validated per hop; **DNS-rebinding TOCTOU** (resolve-then-fetch) — low practical risk since URLs come from OSM tags, not user input.

## 8. Database audit

- Schema: `scrape_cache` + `leads`, indexed (unique on query+name+address, plus query_loc, captured_at). Sensible.
- Queries parameterized (executemany, dict cursor). Transactions committed.
- **Persistence/cleanup:** ✅ durable; ❌ **no cleanup of expired `scrape_cache` rows → unbounded growth.**
- **Concurrency:** global lock + single connection serializes everything; Supabase pooler latency observed **742 ms** on `SELECT COUNT` → every DB-touching request carries ~0.5–1s overhead.
- Missing: connection pool (psycopg2 pool / PgBouncer), insert batching limit, TTL cleanup job.

## 9. Caching audit

- In-memory `TTLCache(256, 600s)` + Postgres mirror. Cache key includes query/location/limit/sources/phone_only/enrich (lowercased) — collision-safe.
- **Stale data:** 600s TTL acceptable for directory data; daily packs refresh anyway.
- **Memory:** bounded (256 entries). **Concurrent requests:** lock-protected, no stampede (DB miss under lock).

## 10. Security audit

- **SSRF:** good (see §7). **Injection:** SQL parameterized; Overpass query built from OSM tags (user query only becomes a `name~` regex — escaped). **DoS:** per-IP limiter 30/min, bounded hit-table (5000). **Secrets:** none in git (verified scan); production env correct on Vercel; **DB password from earlier chat exposure still needs rotation (user action).**
- **Input validation:** FastAPI types + bounds. `limit` validated. ✅
- **CORS:** no CORS middleware → browsers can't read responses cross-origin (fine for API); not an open-CORS risk. **Headers:** no security headers (matterless for API). **Debug:** `/docs` (Swagger) exposed in prod — minor info leak.
- **API key:** string `!=` comparison — **not constant-time** (timing side-channel); low practical risk.
- **X-Forwarded-For trusted** for rate-limit identity — spoofable if ever hosted without a trusted proxy.

## 11. Dependency audit

- All 6 deps pinned and current (fastapi 0.141.1, uvicorn 0.52.3, requests 2.34.2, bs4 4.15.0, cachetools 7.1.7, psycopg2-binary 2.9.10). No known-vuln/obsolete packages. No unnecessary packages. Production-suitable.

## 12. Performance audit

- **Maximum practical load:** single-user/low-concurrency only. 4-worker concurrency across sources + enrichment.
- **Live latency:** cached `export.csv` fast; uncached heavy scrape 7s→40s+; `/health` DB check ~742ms.
- **N+1:** enrichment is the N+1 by design (bounded at 6 sites, 4 workers). OSM API lookups serialized at 1/s → ~6s floor when enriching.
- **Root failure:** **Vercel Hobby `maxDuration=60s` vs worst-case request (Overpass 25+15s + Nominatim + Photon + 6-site enrich ≈ 60–80s) → `FUNCTION_INVOCATION_TIMEOUT`.** Confirmed live: `/health?probe=1` and `NY restaurant enrich=true` 504; cron pack run had 17/58 failures. This is the single biggest production defect.

## 13. Reliability audit

- Source unavailable → handled (mirrors, status reporting). 429/403/5xx → per-source error. Malformed → try/except everywhere.
- **Partial results:** ✅ when a source errors; ❌ when the platform 504s (whole request lost).
- **One source failing while others work:** ✅ by design and demonstrated.

## 14. Testing audit

- **60 unit tests, 16 classes** — excellent coverage of: phone/email extraction, query building, tag mapping, dedupe, enricher, SSRF guard (incl. redirect-to-internal), rate limiter middleware, app payload/cache wiring, DB degradation + wiring, lead-store auth, health probe, leadpack gate/ODbL/base_prefix. **All pass locally.**
- **Gaps:** no live integration test of `/scrape` on Vercel (the probe itself times out!); no coverage metric; no load test; no test for Overpass retry path, `_clean_phone` 7-digit boundary, cross-source dedup.

## 15. Deployment audit

- **Vercel:** correct project (`masood-nasir/scraping-script`), top-level `functions` format, `maxDuration=60, memory=1024`, env set correctly, `/health` liveness OK. **Env mismatch:** production has no `OVERPASS_DEADLINE`/`MAX_RESULTS` tuning to fit the 60s budget.
- **Render:** `render.yaml` (free plan) + README instructions present — viable alternative with no hard 60s request cap.
- **CI:** `tests.yml` runs 60 tests on push/PR. `leadpacks.yml` cron daily + dispatch + path-triggered. ✅
- **Logs:** startup DB errors printed, source warnings logged; no structured/aggregated logging or uptime monitor.

## 16. Git / release audit

- Clean single-branch `main`, history readable, no leaked secrets (`git grep` + full-history scan clean — only the placeholder in `.env.example`). `.gitignore` protects `.env*`, cookies. Reproducible build (pinned deps, CI). **No version tags/changelog** (minor). Deployment source = GitHub→Vercel auto. ✅

## 17. Documentation audit

- Excellent: README (API, env table, deployment, sources, honest phone-picture, ODbL/resale legal), RAPIDAPI_LISTING, GUMROAD_LISTING (copy + pricing + checklist), DISTRIBUTION_PLAN (channels, tracker, kill criterion). **Limitations + troubleshooting honestly documented.** ✅

## 18. End-to-end functional audit

- Query → sources → normalize → dedupe → enrich → cache/DB → JSON/CSV: **works**, verified live (`Melbourne dentist` 50 rows; `export.csv` 200; `/categories` 81; `/leads` 401/403 paths correct). Error path works at app level. ❌ **But the heavy-query path fails end-to-end on Vercel (504).**

## 19. Production-readiness audit

- Can it handle real users? **Only a handful** — no concurrency headroom, Vercel 60s breaks the core flow.
- Survive source failures? ✅ Yes, by design.
- Secure? ✅ Reasonably (SSRF, key-gating, param binding). Minor hardening left.
- Maintainable? ✅ Very (clean, tested, documented).
- Scalable? ❌ Single DB connection + per-instance limiter + 60s platform cap.
- **What breaks first?** The 60s function timeout on `/scrape?enrich=true` / `probe=1` (already breaking). **Second:** the paid-product model — **all 21 sellable packs are committed to a PUBLIC repo with permanent `raw.githubusercontent.com` URLs**, so anyone can download every paid pack for free. Selling them on Gumroad as-is is undermined.
- **What is genuinely production-ready:** the engine, the quality gate, the honest ODbL-compliant data pipeline, docs, testing discipline.
- **What is only demo-quality:** live reliability under the Hobby platform cap; the monetization/delivery path; multi-user scale.

---

## Final verdict

**PASS WITH ISSUES — 67/100.** A well-engineered, honestly documented, well-tested scraper/product pipeline. It is **not yet sales-robust** because of two critical blockers, then a cluster of medium items.

### Critical blockers
1. **Vercel 60s timeout breaks the core flow** (504 on heavy `/scrape`, `probe=1`, and 17/58 cron packs). Must fit the request budget or move hosting.
2. **Paid packs are publicly downloadable** via `docs/leads/` raw URLs → contradicts the Gumroad business model. Must gate delivery.

### High priority
3. Rotate Supabase DB password (user action; chat-exposed credential).
4. `scrape_cache` unbounded growth → add TTL cleanup.
5. Add live uptime monitoring (`UptimeRobot` → `/health`) since the probe currently proves the 504 problem.

### Medium
6. Fix Overpass retry guard (20s) — dead path after slow timeouts.
7. Constant-time API-key compare (`hmac.compare_digest`).
8. `_clean_phone`: require ≥8 digits unless `+`-prefixed (kill 7-digit junk).
9. Cross-source dedup (merge by phone when present, not just name+address).
10. Add live integration test + coverage tooling to CI.
11. Decide Google-Maps source fate (ToS/compliance smell; returns ~nothing).

### Low
12. Tighten `.gitignore` (`.env*` → `.env`, `.env.*`, `!.env.example`).
13. Disable `/docs` in production or accept info leak.
14. Version tags / changelog.
15. Optionally: `/scrape` background enrichment so the response returns fast and enrichment lands in DB only.

### Exact remediation order
1. **Reliability first:** set prod env `OVERPASS_DEADLINE=15`, `ENRICH_MAX_SITES=4`, `MAX_RESULTS=50`; re-verify `/health?probe=1` and a heavy `/scrape` < 55s. If still 504, **move primary hosting to Render free** (no 60s cap) and repoint `LEADPACK_API`. → removes Critical #1.
2. **Monetization second:** stop committing paid packs to the public repo. Keep one free-sample pack public (that's the funnel); deliver paid packs as **Gumroad-hosted file downloads** (generate locally, upload), or move `docs/leads/` to a private repo. Update GUMROAD delivery text. → removes Critical #2.
3. Rotate Supabase password, update `DATABASE_URL` in `.env` + Vercel prod. (user)
4. Add `DELETE FROM scrape_cache WHERE expires_at < now()` cleanup (startup + cron).
5. Set up uptime monitor on `/health`.
6. Apply the medium-security/quality fixes (compare_digest, phone boundary, dedup).
7. CI: add live-probe job + coverage gate.
8. Ship the Gumroad product only after 1–2 are done (kills no sales while broken).