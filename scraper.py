import os
import re
import json
import time
import logging
import threading
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("scraper")

USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 BusinessDirScraper/1.0",
)
REQUEST_TIMEOUT = float(os.environ.get("SCRAPER_TIMEOUT", "20"))
OVER_PASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_DEADLINE = int(os.environ.get("OVERPASS_DEADLINE", "25"))
MAX_BBOX_DEG = float(os.environ.get("MAX_BBOX_DEG", "1.3"))
OVERPASS_RETRIES = int(os.environ.get("OVERPASS_RETRIES", "1"))
ENRICH_MAX_SITES = int(os.environ.get("ENRICH_MAX_SITES", "10"))
ENRICH_USE_OSM_API = os.environ.get("ENRICH_USE_OSM_API", "1") == "1"
ENRICH_DEFAULT = os.environ.get("ENRICH_DEFAULT", "1") == "1"
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "50"))

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}

_GEO_LOCK = threading.Lock()
_GEO_LAST_REQ = 0.0
_GEO_CACHE = {}
_GEO_CACHE_LOCK = threading.Lock()
GEO_CACHE_TTL = int(os.environ.get("GEO_CACHE_TTL", "3600"))


def geocode(search, limit=6):
    """Nominatim lookup honoring the 1 req/s policy, with a shared TTL cache so
    the OSM and Photon scrapers reuse one geocode result per request."""
    search = (search or "").strip()
    if not search:
        return []
    now = time.monotonic()
    key = (search.lower(), limit)
    with _GEO_CACHE_LOCK:
        hit = _GEO_CACHE.get(key)
        if hit and now - hit[0] < GEO_CACHE_TTL:
            return hit[1]
    with _GEO_LOCK:
        global _GEO_LAST_REQ
        now = time.monotonic()
        delay = 1.05 - (now - _GEO_LAST_REQ)
        if delay > 0:
            time.sleep(delay)
        _GEO_LAST_REQ = time.monotonic()
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": search, "format": "jsonv2", "limit": limit},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        return []
    if r.status_code == 403 or r.status_code == 429:
        return []
    if r.status_code != 200:
        return []
    items = r.json() or []
    with _GEO_CACHE_LOCK:
        _GEO_CACHE[key] = (time.monotonic(), items)
    return items


@dataclass
class Business:
    name: str
    phone: str = None
    address: str = None
    website: str = None
    latitude: float = None
    longitude: float = None
    source: str = "openstreetmap"
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


class SourceError(Exception):
    pass


class BaseScraper:
    source = "base"

    def scrape(self, query, location, limit):
        raise NotImplementedError

    def _get(self, url, params=None, headers=None, timeout=None):
        r = requests.get(
            url,
            params=params,
            headers={**BASE_HEADERS, **(headers or {})},
            timeout=timeout or REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r

    def _post(self, url, data=None, headers=None, timeout=None):
        r = requests.post(
            url,
            data=data,
            headers={**BASE_HEADERS, **(headers or {})},
            timeout=timeout or REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r


TAG_RULES = [
    ("property management", r"(property management|property manager)", ["office=property_management"]),
    ("real estate", r"(real[\s-]?estate|realtor|property|estate agent)", ["office~estate|real_estate", "shop~real_estate"]),
    ("restaurant", r"(restaurant|dining|eat|food)", ["amenity=restaurant"]),
    ("cafe", r"(caff[eé]|coffee|coffeehouse|cafe)", ["amenity=cafe"]),
    ("hotel", r"(hotel|motel|lodging|guesthouse|inn)", ["tourism=hotel"]),
    ("dentist", r"(dentist|dental)", ["amenity=dentist"]),
    ("clinic", r"(clinic)", ["amenity=clinic"]),
    ("hospital", r"(hospital|urgent care|medical center)", ["amenity=hospital"]),
    ("doctor", r"(doctor|physician|physiotherapy|pharmacist)", ["amenity=doctors"]),
    ("pharmacy", r"(pharmacy|drugstore|drug store|chemist)", ["amenity=pharmacy"]),
    ("gym", r"(gym|fitness)", ["leisure=fitness_centre", "leisure~gym"]),
    ("kindergarten", r"(kindergarten|preschool|daycare|nursery school)", ["amenity=kindergarten"]),
    ("school", r"(school|college|university|academy)", ["amenity=school", "amenity=college", "amenity=university"]),
    ("bank", r"(bank|credit union)", ["amenity=bank"]),
    ("atm", r"(atm|automatic teller)", ["amenity=atm"]),
    ("fuel", r"(gas station|petrol|fuel|petrol station)", ["amenity=fuel"]),
    ("car rental", r"(car rental|rent a car|cab service|taxi)", ["amenity=car_rental", "amenity=taxi"]),
    ("car repair", r"(auto repair|mechanic|workshop|garage)", ["shop=car_repair", "shop=car"]),
    ("car dealer", r"(car dealer|automall|auto dealer|showroom|pre-?owned cars)", ["shop=car"]),
    ("auto parts", r"(auto parts|car parts|autoparts|motorcycle parts)", ["shop=car_parts", "shop=motorcycle"]),
    ("glazier", r"(glazier|glass repair|glass company|window glass)", ["craft=glazier"]),
    ("tire shop", r"(tire|tyre|wheel alignment)", ["shop=tyres"]),
    ("roofing", r"(roofing|roofer|roof repair)", ["craft=roofer"]),
    ("hvac", r"(hvac|heating|air conditioning|ac repair|furnace)", ["craft=hvac"]),
    ("locksmith", r"(locksmith|lock and key|key cutting)", ["craft=locksmith"]),
    ("painting", r"(painting contractor|house painting|painter)", ["craft=painter"]),
    ("plumber", r"(plumber|plumbing)", ["craft=plumber"]),
    ("electrician", r"(electrician|electrical)", ["craft=electrician"]),
    ("handyman", r"(handyman|handy man|odd jobs|home repairs)", ["craft=handyman"]),
    ("chiropractor", r"(chiropractor|chiropractic)", ["healthcare=chiropractor", "office=chiropractor"]),
    ("tattoo", r"(tattoo|tattoo studio|piercing)", ["shop=tattoo"]),
    ("nail salon", r"(nail salon|nail bar|manicure|pedicure)", ["shop=beauty", "shop=nail_art"]),
    ("salon", r"(salon|beauty parlor|hair salon|hairdresser|barber)", ["shop=hairdresser", "shop=beauty"]),
    ("spa", r"(massage|spa|wellness)", ["shop=beauty", "leisure=spa"]),
    ("golf", r"(golf course|golf club|mini golf)", ["leisure=golf_course"]),
    ("bowling", r"(bowling|bowling alley)", ["leisure=bowling_alley"]),
    ("landscaping", r"(landscap|lawn care|garden service|gardener)", ["shop=garden_centre", "craft=gardener"]),
    ("grocery", r"(grocery|supermarket|grocery store|mart)", ["shop=supermarket", "shop=grocery"]),
    ("liquor", r"(liquor store|liquor|wine store|spirits|off-?licence)", ["shop=alcohol"]),
    ("bakery", r"(bakery|baker)", ["shop=bakery"]),
    ("travel", r"(travel agent|tourism office)", ["office=travel_agent"]),
    ("laundry", r"(laundry|dry cleaner|dry cleaning)", ["shop=laundry", "shop=dry_cleaning"]),
    ("electronics", r"(electronics|electrical shop)", ["shop=electronics"]),
    ("hardware", r"(hardware|building material)", ["shop=hardware"]),
    ("clothing", r"(clothing|clothes|apparel|fashion)", ["shop=clothes"]),
    ("furniture", r"(furniture|furnishings)", ["shop=furniture"]),
    ("jewelry", r"(jewelry|jewellery)", ["shop=jewelry"]),
    ("footwear", r"(footwear|shoes)", ["shop=shoes"]),
    ("optometrist", r"(optometrist|optician|eyeglass|optical)", ["shop=optician"]),
    ("florist", r"(florist|flower shop)", ["shop=florist"]),
    ("bookstore", r"(bookstore|book shop|stationery)", ["shop=books", "shop=stationery"]),
    ("lawyer", r"(lawyer|advocate|attorney|legal)", ["office=lawyer"]),
    ("accountant", r"(accountant|accounting|bookkeeper|tax consultant)", ["office=accountant"]),
    ("insurance", r"(insurance)", ["office=insurance"]),
    ("notary", r"(notary|notary public)", ["office=notary"]),
    ("surveyor", r"(surveyor|land survey)", ["office=surveyor"]),
    ("engineer", r"(engineer|engineering)", ["office=engineer"]),
    ("medical supply", r"(medical supply|medical equipment|surgical supply|medical store)", ["shop=medical_supply"]),
    ("financial advisor", r"(financial advisor|financial planner|wealth management|investment advisor)", ["office=financial_advisor", "office=financial"]),
    ("it services", r"(software|information technology|it services|computer services)", ["office=it", "office=computer"]),
    ("telecom", r"(telecom|mobile shop|phone shop)", ["shop=mobile_phone"]),
    ("general contractor", r"(contractor|construction)", ["office=construction_company", "shop=construction_materials"]),
    ("architecture", r"(architecture|architect)", ["office=architect"]),
    ("estate agency", r"(real estate|property dealer|estate)", ["office=estate_agent"]),
    ("photo", r"(photographer|photography)", ["shop=photo", "craft=photographer"]),
    ("pet", r"(pet shop|veterinary|veterinarian|vets)", ["shop=pet", "amenity=veterinary"]),
    ("bank branch", r"(branch)", ["amenity=bank"]),
    ("civic", r"(post office|tax office|police station|fire station)", ["amenity=post_office", "amenity=police", "amenity=fire_station"]),
    ("transport", r"(bus station|train station|airport)", ["highway=bus_stop", "railway=station", "aeroway=aerodrome"]),
    ("bar", r"(\bbar\b|pub|nightclub|lounge)", ["amenity=bar", "amenity=pub", "amenity=nightclub"]),
    ("cinema", r"(cinema|movie theater|movie theatre|multiplex)", ["amenity=cinema"]),
    ("printing", r"(print shop|printing|copyshop|copy shop)", ["shop=copyshop"]),
    ("place of worship", r"(church|mosque|temple|gurdwara|synagogue|cathedral)", ["amenity=place_of_worship"]),
    ("funeral", r"(funeral|crematorium|undertaker)", ["shop=funeral_directors", "amenity=crematorium"]),
    ("sports centre", r"(sports centre|sports center|sports club|stadium|tennis club|golf club)", ["leisure=sports_centre", "leisure=stadium", "leisure=golf_course"]),
    ("library", r"(library)", ["amenity=library"]),
    ("marina", r"(marina|boat yard|yacht club|boat rentals)", ["leisure=marina"]),
    ("campsite", r"(campground|campsite|caravan park|cabin rental)", ["tourism=camp_site", "tourism=caravan_site"]),
    ("parking", r"(parking garage|parking lot|car park)", ["amenity=parking"]),
    ("toilet", r"(public toilet|restroom|washroom)", ["amenity=toilets"]),
    ("park", r"(park|playground|garden)", ["leisure=park", "leisure=playground", "leisure=garden"]),
]

PHONE_TEXT_RE = re.compile(
    r"(?:(?:\+?\d{1,4})[\s\-().]*)?"
    r"(?:\(\d{2,5}\)[\s\-().]*|\d{2,5}[\s\-().]{0,2})\d{3}[\s\-().]{0,2}\d{3,4}[\s\-().]{0,2}\d{0,4}"
)
DATE_LIKE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")

SOCIAL_DOMAINS = (
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "wa.me", "t.me", "snapchat.com", "pinterest.com",
)


class OSMScraper(BaseScraper):
    source = "openstreetmap"

    def _resolve_bbox(self, query, location):
        search = (location or "").strip() or (query or "").strip()
        items = self._geocode(search)
        if not items:
            raise SourceError(f"geocoding failed for {search!r}: no location found")
        best = max(items, key=self._bbox_area)
        s, n, w, e = (float(x) for x in best["boundingbox"])
        if (e - w) > MAX_BBOX_DEG or (n - s) > MAX_BBOX_DEG:
            c_lat = (s + n) / 2.0
            c_lon = (w + e) / 2.0
            half = MAX_BBOX_DEG / 2.0
            s, n = c_lat - half, c_lat + half
            w, e = c_lon - half, c_lon + half
        return [s, n, w, e]

    @staticmethod
    def _geocode(search):
        return geocode(search, limit=6)

    @staticmethod
    def _bbox_area(item):
        b = item.get("boundingbox") or [0, 0, 0, 0]
        try:
            s, n, w, e = (float(x) for x in b)
        except (TypeError, ValueError):
            return 0.0
        return (e - w) * (n - s)

    def _tag_filters(self, query):
        q = (query or "").strip()
        for _, pattern, filters in TAG_RULES:
            if re.search(pattern, q, re.IGNORECASE):
                return filters
        escaped = re.escape(q)
        return [f"name~{escaped},i"]

    def _build_query(self, query, location, limit, light=False):
        s, n, w, e = self._resolve_bbox(query, location)
        filters = self._tag_filters(query)
        members = []
        for f in filters:
            if "=" in f:
                key, val = f.split("=", 1)
                cond = f'["{key}"="{val}"]'
            elif "~" in f:
                key, val = f.split("~", 1)
                flag = ",i" if val.endswith(",i") else ""
                if flag:
                    val = val[:-2]
                cond = f'["{key}"~"{val}"{flag}]'
            else:
                cond = f
            members.append(f"node{cond}({s:.6f},{w:.6f},{n:.6f},{e:.6f})")
            if not light:
                members.append(f"way{cond}({s:.6f},{w:.6f},{n:.6f},{e:.6f})")
        if not members:
            members = [f'node["name"]({s:.6f},{w:.6f},{n:.6f},{e:.6f})']
            if not light:
                members.append(f'way["name"]({s:.6f},{w:.6f},{n:.6f},{e:.6f})')
        group = " ".join(members)
        return (
            f"[out:json][timeout:{OVERPASS_DEADLINE}];"
            f"({group})->.a;"
            f".a out center tags {limit};"
        )

    def scrape(self, query, location, limit):
        t0 = time.monotonic()
        data = self._run_overpass(query, location, limit)
        if data is None and OVERPASS_RETRIES > 0 and (time.monotonic() - t0) < 20:
            data = self._run_overpass(query, location, limit, light=True)
        if data is None:
            raise SourceError("openstreetmap source unreachable (timeout or rate limited)")

        businesses = []
        for el in data.get("elements", []):
            tags = el.get("tags", {}) or {}
            name = tags.get("name") or tags.get("official_name") or tags.get("short_name")
            if not name:
                continue
            addr = self._format_address(tags)
            phone = (
                tags.get("phone")
                or tags.get("contact:phone")
                or tags.get("tel")
                or tags.get("contact:mobile")
            )
            phone = _clean_phone(phone)
            website = tags.get("website") or tags.get("contact:website") or tags.get("url")
            lat = el.get("lat")
            lon = el.get("lon")
            if lat is None:
                center = el.get("center") or {}
                lat, lon = center.get("lat"), center.get("lon")
            businesses.append(
                Business(
                    name=name,
                    phone=phone,
                    address=addr,
                    website=website,
                    latitude=lat,
                    longitude=lon,
                    source=self.source,
                    extra={"osm_type": el.get("type"), "osm_id": el.get("id")},
                )
            )
        return businesses

    def _run_overpass(self, query, location, limit, light=False):
        overpass_query = self._build_query(query, location, limit, light=light)
        endpoints = OVER_PASS_ENDPOINTS[:2] if light else OVER_PASS_ENDPOINTS
        for ep in endpoints:
            try:
                r = requests.post(
                    ep,
                    data={"data": overpass_query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=min(OVERPASS_DEADLINE, 18),
                )
                if r.status_code == 429:
                    time.sleep(0.6)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception:
                continue
        return None

    @staticmethod
    def _format_address(tags):
        parts = []
        for k in (
            "addr:housenumber",
            "addr:street",
            "addr:suburb",
            "addr:district",
            "addr:city",
            "addr:province",
            "addr:postcode",
            "addr:country",
        ):
            v = tags.get(k)
            if v and v not in parts:
                parts.append(v)
        return ", ".join(parts) if parts else None


PHOTON_TAG_MAP = {
    "property management": ("office", "property_management"),
    "real estate": ("office", "estate_agent"),
    "restaurant": ("amenity", "restaurant"),
    "cafe": ("amenity", "cafe"),
    "hotel": ("tourism", "hotel"),
    "dentist": ("amenity", "dentist"),
    "clinic": ("amenity", "clinic"),
    "hospital": ("amenity", "hospital"),
    "doctor": ("amenity", "doctors"),
    "pharmacy": ("amenity", "pharmacy"),
    "gym": ("leisure", "fitness_centre"),
    "kindergarten": ("amenity", "kindergarten"),
    "school": ("amenity", "school"),
    "bank": ("amenity", "bank"),
    "atm": ("amenity", "atm"),
    "fuel": ("amenity", "fuel"),
    "car rental": ("amenity", "car_rental"),
    "car repair": ("shop", "car_repair"),
    "car dealer": ("shop", "car"),
    "auto parts": ("shop", "car_parts"),
    "glazier": ("craft", "glazier"),
    "tire shop": ("shop", "tyres"),
    "roofing": ("craft", "roofer"),
    "hvac": ("craft", "hvac"),
    "locksmith": ("craft", "locksmith"),
    "painting": ("craft", "painter"),
    "plumber": ("craft", "plumber"),
    "electrician": ("craft", "electrician"),
    "handyman": ("craft", "handyman"),
    "chiropractor": ("healthcare", "chiropractor"),
    "tattoo": ("shop", "tattoo"),
    "nail salon": ("shop", "beauty"),
    "salon": ("shop", "hairdresser"),
    "barber": ("shop", "barber"),
    "spa": ("shop", "beauty"),
    "golf": ("leisure", "golf_course"),
    "bowling": ("leisure", "bowling_alley"),
    "landscaping": ("craft", "gardener"),
    "supermarket": ("shop", "supermarket"),
    "bakery": ("shop", "bakery"),
    "travel": ("office", "travel_agent"),
    "laundry": ("shop", "laundry"),
    "florist": ("shop", "florist"),
    "bookstore": ("shop", "books"),
    "lawyer": ("office", "lawyer"),
    "accountant": ("office", "accountant"),
    "insurance": ("office", "insurance"),
    "notary": ("office", "notary"),
    "surveyor": ("office", "surveyor"),
    "engineer": ("office", "engineer"),
    "medical supply": ("shop", "medical_supply"),
    "financial advisor": ("office", "financial_advisor"),
    "it": ("office", "it"),
    "telecom": ("shop", "mobile_phone"),
    "architect": ("office", "architect"),
    "photo": ("craft", "photographer"),
    "pet": ("amenity", "veterinary"),
    "bar": ("amenity", "bar"),
    "nightclub": ("amenity", "nightclub"),
    "cinema": ("amenity", "cinema"),
    "printing": ("shop", "copyshop"),
    "place of worship": ("amenity", "place_of_worship"),
    "funeral": ("shop", "funeral_directors"),
    "sports centre": ("leisure", "sports_centre"),
    "library": ("amenity", "library"),
    "marina": ("leisure", "marina"),
    "campsite": ("tourism", "camp_site"),
    "parking": ("amenity", "parking"),
    "park": ("leisure", "park"),
}
MAX_PHOTON_KM = float(os.environ.get("MAX_PHOTON_KM", "120"))


class PhotonScraper(BaseScraper):
    source = "photon"
    ENDPOINT = "https://photon.komoot.io/api/"

    def _location_center(self, query, location):
        search = (location or "").strip() or (query or "").strip()
        items = geocode(search, limit=6)
        if not items:
            return None
        try:
            return float(items[0]["lat"]), float(items[0]["lon"])
        except (KeyError, TypeError, ValueError):
            return None

    def scrape(self, query, location, limit):
        center = self._location_center(query, location)
        q = (query or "").strip()
        tag = self._mapped_tag(q)

        params = {"q": q, "limit": min(limit * 2, 50), "lang": "en"}
        if center:
            params["lat"], params["lon"] = center[0], center[1]
        if tag:
            params["osm_tag"] = f"{tag[0]}:{tag[1]}"

        features = self._search(params)
        if tag and not features:
            params.pop("osm_tag", None)
            features = self._search(params)

        businesses = self._to_businesses(features, center)
        return businesses[:limit]

    def _search(self, params):
        r = requests.get(
            self.ENDPOINT,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 403 or r.status_code == 429:
            raise SourceError(f"photon http {r.status_code}")
        r.raise_for_status()
        return (r.json() or {}).get("features", []) or []

    @staticmethod
    def _mapped_tag(q):
        lowered = q.lower().replace(" ", "")
        best, best_len = None, -1
        for key, tag in PHOTON_TAG_MAP.items():
            k = key.replace(" ", "")
            if k in lowered and len(k) > best_len:
                best, best_len = tag, len(k)
        return best

    def _to_businesses(self, features, center):
        businesses = []
        for f in features:
            p = f.get("properties", {})
            name = p.get("name")
            if not name:
                continue
            geom = f.get("geometry", {})
            coords = geom.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            b = Business(
                name=name,
                address=self._format_address(p),
                latitude=lat,
                longitude=lon,
                source=self.source,
                extra={
                    "osm_type": p.get("osm_type"),
                    "osm_id": p.get("osm_id"),
                    "category": f"{p.get('osm_key')}:{p.get('osm_value')}" if p.get("osm_value") else p.get("osm_key"),
                },
            )
            businesses.append(b)
        if center:
            businesses = [
                b
                for b in businesses
                if b.latitude is not None
                and _haversine(center[0], center[1], b.latitude, b.longitude) <= MAX_PHOTON_KM
            ]
            businesses.sort(
                key=lambda b: _haversine(center[0], center[1], b.latitude, b.longitude)
                if b.latitude is not None
                else 1e9
            )
        return businesses

    @staticmethod
    def _format_address(p):
        parts = []
        street = p.get("street")
        hnum = p.get("housenumber") or p.get("houseNumber")
        if hnum and street:
            parts.append(f"{street} {hnum}")
        elif street:
            parts.append(street)
        for key in ("locality", "district", "city", "state", "postcode"):
            v = p.get(key)
            if v and v not in parts[-1:] and v not in parts:
                parts.append(v)
        return ", ".join(parts) if parts else None


class GoogleMapsScraper(BaseScraper):
    source = "google_maps"

    def scrape(self, query, location, limit):
        search = f"{query} {location}".strip() if location else query
        url = "https://www.google.com/maps/search/" + requests.utils.quote(search)
        try:
            r = self._get(url)
        except Exception as exc:
            raise SourceError(f"google maps request failed: {exc}")

        soup = BeautifulSoup(r.text, "html.parser")
        businesses = []

        anchors = soup.select('a[href*="/maps/place/"]')
        seen = set()
        for a in anchors[:limit]:
            name = (a.get("aria-label") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            span = a.find_next("span", class_=re.compile(r"Io6YTe|fontBodyMedium"))
            addr = self._nearby_text(a, seen)
            phone = self._nearby_phone(a)
            businesses.append(
                Business(
                    name=name,
                    phone=phone,
                    address=addr,
                    source=self.source,
                    extra={"degraded": True},
                )
            )

        if not businesses:
            businesses = self._from_state(r.text, limit)
        return businesses

    def _nearby_text(self, node, seen):
        parent = node.parent
        if not parent:
            return None
        spans = parent.select("span")
        for s in spans:
            txt = s.get_text(" ", strip=True)
            if txt and txt not in seen and "," in txt:
                seen.add(txt)
                return txt[:180]
        return None

    @staticmethod
    def _nearby_phone(node):
        for a in node.parent.select('a[href^="tel:"]') if node.parent else []:
            return a.get_text(strip=True) or a.get("href", "").replace("tel:", "")
        return None

    def _from_state(self, html, limit):
        m = re.search(r"window\.APP_INITIALIZATION_STATE\s*=\s*", html)
        if not m:
            return []
        raw = self._balanced(m.end(), html)
        if raw is None:
            return []
        try:
            state = json.loads(raw)
        except Exception:
            return []
        out = []
        for item in self._scan(state, limit):
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def _scan(self, obj, limit, seen=None):
        seen = seen or set()
        results = []
        if isinstance(obj, dict):
            if "name" in obj and any(isinstance(obj.get(k), str) for k in ("name", "address")):
                name = obj.get("name")
                if isinstance(name, str) and name and not name.startswith("Google"):
                    address = self._find_address(obj)
                    phone = self._find_phone(obj)
                    key = (name, address)
                    if key not in seen and (address or phone):
                        seen.add(key)
                        results.append(
                            Business(name=name, phone=phone, address=address, source=self.source)
                        )
            for v in obj.values():
                results.extend(self._scan(v, limit, seen))
                if len(results) >= limit:
                    return results
        elif isinstance(obj, list):
            for v in obj:
                results.extend(self._scan(v, limit, seen))
                if len(results) >= limit:
                    return results
        return results

    @staticmethod
    def _find_address(obj):
        for k in ("address", "addressLines", "fullAddress"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 3:
                return v
        return None

    @staticmethod
    def _find_phone(obj):
        for k in ("phone", "tel", "telephone", "internationalPhoneNumber"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) >= 7:
                return v
        return None

    def _balanced(self, start, html):
        depth, instr, esc = 0, False, False
        for j in range(start, len(html)):
            ch = html[j]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
                continue
            if ch == '"':
                instr = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return html[start : j + 1]
        return None


def _clean_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw or "")
    if not digits or not (7 <= len(digits) <= 15):
        return None
    return ("+" + digits) if str(raw).strip().startswith("+") else digits


def extract_phone_from_html(html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for a in soup.select('a[href*="tel:"]'):
        href = a.get("href", "")
        m = re.search(r"tel:([+0-9\s\-().]+)", href)
        if m:
            candidates.append(m.group(1))
        txt = a.get_text(strip=True)
        if re.search(r"\d", txt):
            candidates.append(txt)

    for el in soup.select(
        '[itemprop="telephone"], meta[name="telephone"], meta[property="telephone"]'
    ):
        candidates.append(el.get("content") or el.get_text(strip=True))

    for sc in soup.select('script[type="application/ld+json"]'):
        text = (sc.string or sc.get_text() or "")
        try:
            payload = json.loads(text)
            for item in _walk_ld(payload):
                tel = item.get("telephone") if isinstance(item, dict) else None
                if isinstance(tel, str):
                    candidates.append(tel)
        except Exception:
            for m in re.finditer(r'"telephone"\s*:\s*"([^"]*)"', text):
                candidates.append(m.group(1))
            for m in re.finditer(r'"telephone"\s*:\s*(\+?[\d\s\-()]+)', text):
                candidates.append(m.group(1))

    for c in candidates:
        clean = _clean_phone(c)
        if clean:
            return clean

    body = soup.get_text(" ", strip=True)
    if body:
        for m in re.finditer(PHONE_TEXT_RE, body[:60000]):
            raw = m.group(0)
            if DATE_LIKE_RE.fullmatch(raw):
                continue
            clean = _clean_phone(raw)
            if clean:
                return clean
    return None


EMAIL_SKIP_DOMAINS = {"example.com", "example.org", "example.net", "example.edu", "test.com"}


def extract_emails_from_html(html, limit=3):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    email_re = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

    def add(addr):
        if not addr:
            return
        addr = addr.strip().lower()
        if len(addr) > 254:
            return
        if addr in seen:
            return
        seen.add(addr)
        domain = addr.split("@", 1)[-1] if "@" in addr else ""
        m = email_re.fullmatch(addr)
        if m and domain not in EMAIL_SKIP_DOMAINS and not any(
            t in addr for t in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
        ):
            found.append(addr)

    for a in soup.select('a[href^="mailto:"]'):
        href = a.get("href", "")
        addr = href.split(":", 1)[-1].split("?", 1)[0].strip()
        add(addr)
        add(a.get_text(strip=True))

    for el in soup.select(
        '[itemprop="email"], meta[name="email"], meta[property="email"], a[itemprop="email"]'
    ):
        add(el.get("content") or el.get_text(strip=True))

    for sc in soup.select('script[type="application/ld+json"]'):
        text = (sc.string or sc.get_text() or "")
        try:
            payload = json.loads(text)
            for item in _walk_ld(payload):
                if isinstance(item, dict):
                    add(item.get("email") if isinstance(item.get("email"), str) else None)
        except Exception:
            for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', text):
                add(m.group(1))

    if len(found) < limit:
        body = soup.get_text(" ", strip=True)[:60000]
        for m in re.finditer(email_re, body):
            add(m.group(0))
            if len(found) >= limit:
                break
    return found[:limit]


def _walk_ld(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_ld(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_ld(v)


def _haversine(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt

    rlat1, rlon1, rlat2, rlon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def _is_safe_url(url):
    """Reject URLs that point at internal/private/loopback hosts (SSRF guard)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return False
    if not re.match(r"^[a-z0-9._-]+$", host):
        return False
    if host.count(".") == 0:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


class WebsitePhoneEnricher:
    def __init__(self):
        self._osm_rate_lock = threading.Lock()
        self._last_osm_req = 0.0

    def enrich(self, businesses, max_sites=None):
        max_sites = max_sites if max_sites is not None else ENRICH_MAX_SITES
        targets = []
        for b in businesses:
            if b.phone:
                continue
            if b.website or (
                ENRICH_USE_OSM_API and b.extra.get("osm_type") and b.extra.get("osm_id")
            ):
                targets.append(b)
        targets = targets[:max_sites]
        if not targets:
            return businesses

        with ThreadPoolExecutor(max_workers=min(4, len(targets))) as ex:
            futures = {ex.submit(self._process, b): b for b in targets}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    pass
        return businesses

    def _process(self, b):
        if b.phone:
            return
        if not b.website:
            b.website = self._osm_website(
                b.extra.get("osm_type"), b.extra.get("osm_id")
            )
        if not b.website or self._is_social(b.website):
            return
        html = self._fetch(self._normalize_url(b.website))
        if not html:
            return
        phone = extract_phone_from_html(html)
        if phone:
            b.phone = phone
            b.extra["phone_via"] = "website"
        emails = extract_emails_from_html(html, limit=2)
        if emails:
            b.extra["email"] = emails

    @staticmethod
    def _is_social(url):
        return any(d in url.lower() for d in SOCIAL_DOMAINS)

    @staticmethod
    def _normalize_url(url):
        url = url.strip()
        if "//" not in url:
            url = "https://" + url
        return url

    def _osm_website(self, otype, oid):
        if not otype or not oid:
            return None
        mapped = {"N": "node", "W": "way", "R": "relation"}.get(str(otype).upper(), str(otype))
        if mapped not in ("node", "way", "relation"):
            return None
        with self._osm_rate_lock:
            delay = 1.0 - (time.monotonic() - self._last_osm_req)
            if delay > 0:
                time.sleep(delay)
            self._last_osm_req = time.monotonic()
        try:
            r = requests.get(
                f"https://api.openstreetmap.org/api/0.6/{mapped}/{int(oid)}.json",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            el = (r.json().get("elements") or [{}])[0]
            tags = el.get("tags") or {}
            return (
                tags.get("website")
                or tags.get("contact:website")
                or tags.get("url")
            )
        except Exception:
            return None

    @staticmethod
    def _fetch(url):
        try:
            current = url
            with requests.Session() as s:
                for _ in range(4):
                    if not _is_safe_url(current):
                        return None
                    r = s.get(
                        current,
                        headers={"User-Agent": USER_AGENT},
                        timeout=7,
                        stream=True,
                        allow_redirects=False,
                    )
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("Location")
                        r.close()
                        if not loc:
                            return None
                        current = requests.utils.urljoin(current, loc)
                        continue
                    if r.status_code != 200:
                        return None
                    chunks = []
                    total = 0
                    for chunk in r.iter_content(65536):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > 350000:
                            break
                    return b"".join(chunks).decode("utf-8", errors="ignore")
        except Exception:
            return None
        return None


def dedupe(businesses):
    seen = set()
    out = []
    for b in businesses:
        key = (
            re.sub(r"[^a-z0-9]", "", (b.name or "").lower()),
            re.sub(r"[^a-z0-9]", "", (b.address or "").lower()),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def search_all(query, location, limit=20, sources=None, phone_only=False, enrich=None):
    query = (query or "").strip()
    location = (location or "").strip()
    limit = max(1, min(int(limit or 20), MAX_RESULTS))
    if enrich is None:
        enrich = ENRICH_DEFAULT
    requested = [s.strip().lower() for s in (sources or "").split(",") if s.strip()]
    if not requested or requested == ["auto"]:
        requested = ["openstreetmap", "photon"]

    scrapers = {
        "openstreetmap": OSMScraper(),
        "photon": PhotonScraper(),
        "google_maps": GoogleMapsScraper(),
    }
    by_source = {k: {"status": "ok", "error": None, "service": k} for k in requested}

    def run_one(name):
        scraper = scrapers.get(name)
        if scraper is None:
            by_source[name] = {"status": "error", "error": "unknown source", "service": name}
            return name, []
        try:
            items = scraper.scrape(query, location, limit)
            by_source[name] = {"status": "ok", "error": None, "service": name}
            return name, items
        except Exception as exc:
            logger.warning("scrape source=%s failed: %s", name, exc)
            by_source[name] = {"status": "error", "error": str(exc)[:300], "service": name}
            return name, []

    all_businesses = []
    if requested:
        with ThreadPoolExecutor(max_workers=min(len(requested), 4)) as ex:
            futures = [ex.submit(run_one, name) for name in requested]
            for fut in as_completed(futures):
                _, items = fut.result()
                all_businesses.extend(items)

    merged = dedupe(all_businesses)
    enriched_count = 0
    if enrich:
        before = sum(1 for b in merged if b.phone)
        merged = WebsitePhoneEnricher().enrich(merged)
        enriched_count = sum(1 for b in merged if b.phone) - before
    if phone_only:
        merged = [b for b in merged if b.phone]
    return merged[:limit], by_source, enriched_count