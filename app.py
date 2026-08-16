import os
import threading
import time as _time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from cachetools import TTLCache

from scraper import search_all

app = FastAPI(
    title="Business Directory Scraper API",
    version="1.0.0",
    description=(
        "Scrape business **name**, **phone** and **address** data from public web "
        "sources (OpenStreetMap, Photon, and a best-effort Google Maps parser) for "
        "any query + location worldwide. No API keys for the upstream sources are "
        "required.\n\n"
        "### Quick start\n\n"
        "`GET /scrape?query=restaurant&location=New York` returns up to 50 "
        "businesses with name, phone, address, website, latitude, longitude and "
        "source. Set `enrich=true` (default) to try pulling phone numbers from the "
        "business's own website. Use `sources=openstreetmap,photon` for the most "
        "reliable free sources.\n\n"
        "### Example response\n\n"
        "```json\n"
        '{"query": "restaurant", "location": "New York", "count": 50, '
        '"phones_enriched": 4, "results": [{"name": "Grand Central Oyster Bar '
        'and Restaurant", "phone": "2124906650", "address": "East 42nd Street '
        '89, Midtown, Manhattan, New York, 10168", "website": '
        '"https://www.oysterbarny.com/", "latitude": 40.7524, "longitude": '
        '-73.9773, "source": "photon", "extra": {"phone_via": "website"}}]}'
        "\n```"
    ),
    contact={"name": "Business Directory Scraper", "url": "https://scraping-script-xi.vercel.app/"},
    license_info={"name": "MIT"},
)

CACHE = TTLCache(maxsize=256, ttl=600)
CACHE_LOCK = threading.Lock()

APP_ORG = "web-scraper-demo/1.0"

RATE_LIMIT_PER_IP = int(os.environ.get("RATE_LIMIT_PER_IP", "30"))
RATE_LIMIT_WINDOW = float(os.environ.get("RATE_LIMIT_WINDOW", "60"))
_RATE_HITS = {}
_RATE_LOCK = threading.Lock()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if RATE_LIMIT_PER_IP <= 0:
        return await call_next(request)
    fwd = request.headers.get("x-forwarded-for")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))
    now = _time.monotonic()
    with _RATE_LOCK:
        hits = [t for t in _RATE_HITS.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(hits) >= RATE_LIMIT_PER_IP:
            _RATE_HITS[ip] = hits
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded, please slow down"},
                headers={"Retry-After": str(int(RATE_LIMIT_WINDOW))},
            )
        hits.append(now)
        _RATE_HITS[ip] = hits
    return await call_next(request)


@app.get("/")
def index():
    return {
        "name": "Business Directory Scraper",
        "usage": "/scrape?query=RealEstate&location=Karachi",
        "sources": ["openstreetmap", "photon", "google_maps"],
        "documentation": "/docs",
    }


@app.get("/scrape", response_model=dict, summary="Scrape business directory data")
def scrape(
    query: str = Query(
        ...,
        min_length=1,
        description="Business type / keyword to search for, e.g. RealEstate, restaurant, hotel, dentist, gym, plumber, lawyer.",
        examples=["restaurant"],
    ),
    location: Optional[str] = Query(
        None,
        description="City or area name (worldwide), e.g. New York, London, Karachi, Dubai (optional for global search).",
        examples=["New York"],
    ),
    limit: int = Query(
        20, ge=1, le=50, description="Maximum number of results to return (1..50).",
        examples=[50],
    ),
    sources: str = Query(
        "auto",
        description="Comma-separated source list: openstreetmap, photon, google_maps, or auto.",
        examples=["openstreetmap,photon"],
    ),
    phone_only: bool = Query(
        False, description="Return only records that have a phone number.",
    ),
    enrich: bool = Query(
        True, description="Try to find phone numbers on the business's own website (free enrichment).",
    ),
):
    cache_key = (
        query.strip().lower(),
        (location or "").strip().lower(),
        min(limit, 50),
        sources.strip().lower(),
        phone_only,
        enrich,
    )
    with CACHE_LOCK:
        hit = CACHE.get(cache_key)
        if hit is not None:
            return hit

    results, sources_status, enriched = search_all(
        query=query,
        location=location or "",
        limit=limit,
        sources=sources,
        phone_only=phone_only,
        enrich=enrich,
    )

    payload = {
        "query": query,
        "location": location or "",
        "limit": limit,
        "count": len(results),
        "phone_only": phone_only,
        "enrich": enrich,
        "phones_enriched": enriched,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [b.as_dict() for b in results],
        "sources": sources_status,
    }
    CACHE[cache_key] = payload
    return payload


@app.get("/health")
def health():
    return {"status": "ok"}