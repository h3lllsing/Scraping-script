from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query
from cachetools import TTLCache

from scraper import search_all

app = FastAPI(
    title="Business Directory Scraper",
    version="1.0.0",
    description="Scrapes business name, phone and address data from public web sources "
    "(OpenStreetMap, Photon, and a best-effort Google Maps parser). No API keys required.",
)

CACHE = TTLCache(maxsize=256, ttl=600)

APP_ORG = "web-scraper-demo/1.0"


@app.get("/")
def index():
    return {
        "name": "Business Directory Scraper",
        "usage": "/scrape?query=RealEstate&location=Karachi",
        "sources": ["openstreetmap", "photon", "google_maps"],
        "documentation": "/docs",
    }


@app.get("/scrape", response_model=dict)
def scrape(
    query: str = Query(..., min_length=1, description="Business type or query, e.g. RealEstate"),
    location: Optional[str] = Query(None, description="City or area, e.g. Karachi"),
    limit: int = Query(20, ge=1, le=50, description="Maximum number of results"),
    sources: str = Query(
        "auto",
        description="Comma-separated source list: openstreetmap, photon, google_maps, auto",
    ),
    phone_only: bool = Query(False, description="Return only businesses that have a phone number"),
    enrich: bool = Query(
        True, description="Try to find phone numbers on the business's own website (free)"
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