import os
import re
import json
import time
from dataclasses import dataclass, field, asdict

import requests
from bs4 import BeautifulSoup

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
OVERPASS_DEADLINE = int(os.environ.get("OVERPASS_DEADLINE", "45"))
MAX_BBOX_DEG = float(os.environ.get("MAX_BBOX_DEG", "1.3"))
OVERPASS_RETRIES = int(os.environ.get("OVERPASS_RETRIES", "1"))

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}


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
    ("real estate", r"(real[\s-]?estate|realtor|property|estate agent)", ["office~estate|real_estate", "shop~real_estate"]),
    ("restaurant", r"(restaurant|dining|eat|food)", ["amenity=restaurant"]),
    ("cafe", r"(caff[eé]|coffee|coffeehouse|cafe)", ["amenity=cafe"]),
    ("hotel", r"(hotel|motel|lodging|guesthouse|inn)", ["tourism=hotel"]),
    ("dentist", r"(dentist|dental)", ["amenity=dentist"]),
    ("clinic", r"(clinic)", ["amenity=clinic"]),
    ("doctor", r"(doctor|physician|physiotherapy|pharmacist)", ["amenity=doctors"]),
    ("pharmacy", r"(pharmacy|drugstore|drug store|chemist)", ["amenity=pharmacy"]),
    ("gym", r"(gym|fitness)", ["leisure=fitness_centre", "leisure~gym"]),
    ("school", r"(school|college|university|academy)", ["amenity=school", "amenity=college", "amenity=university"]),
    ("bank", r"(bank|credit union)", ["amenity=bank"]),
    ("atm", r"(atm|automatic teller)", ["amenity=atm"]),
    ("fuel", r"(gas station|petrol|fuel|petrol station)", ["amenity=fuel"]),
    ("car rental", r"(car rental|rent a car|cab service|taxi)", ["amenity=car_rental", "amenity=taxi"]),
    ("car repair", r"(auto repair|mechanic|workshop|garage)", ["shop=car_repair", "shop=car"]),
    ("plumber", r"(plumber|plumbing)", ["craft=plumber"]),
    ("electrician", r"(electrician|electrical)", ["craft=electrician"]),
    ("salon", r"(salon|beauty parlor|hair salon|hairdresser|barber)", ["shop=hairdresser", "shop=beauty"]),
    ("grocery", r"(grocery|supermarket|grocery store|mart)", ["shop=supermarket", "shop=grocery"]),
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
    ("lawyer", r"(lawyer|advocate|attorney|legal)", ["office=lawyer"]),
    ("accountant", r"(accountant|accounting|bookkeeper|tax consultant)", ["office=accountant"]),
    ("insurance", r"(insurance)", ["office=insurance"]),
    ("notary", r"(notary|notary public)", ["office=notary"]),
    ("engineer", r"(engineer|engineering)", ["office=engineer"]),
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
    ("library", r"(library)", ["amenity=library"]),
    ("toilet", r"(public toilet|restroom|washroom)", ["amenity=toilets"]),
    ("park", r"(park|playground|garden)", ["leisure=park", "leisure=playground", "leisure=garden"]),
]

FALLBACK_GENERIC_KEYS = "amenity|shop|office|tourism|leisure|craft|highway|railway"


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
        params = {"q": search, "format": "jsonv2", "limit": 6}
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 403:
            return []
        r.raise_for_status()
        return r.json() or []

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
        return [f'name~"{escaped}",i']

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
                cond = f'["{key}"~"{val}"]'
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
        data = self._run_overpass(query, location, limit)
        if data is None and OVERPASS_RETRIES > 0:
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
        for ep in OVER_PASS_ENDPOINTS:
            try:
                r = requests.post(
                    ep,
                    data={"data": overpass_query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=min(OVERPASS_DEADLINE, 30),
                )
                if r.status_code == 429:
                    continue
                r.raise_for_status()
                return r.json()
            except Exception:
                continue
        return None

    @staticmethod
    def _format_address(tags):
        parts = []
        for k in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode", "addr:country"):
            v = tags.get(k)
            if v:
                parts.append(v)
        return ", ".join(parts) if parts else None


PHOTON_TAG_MAP = {
    "real estate": ("office", "estate_agent"),
    "restaurant": ("amenity", "restaurant"),
    "cafe": ("amenity", "cafe"),
    "hotel": ("tourism", "hotel"),
    "dentist": ("amenity", "dentist"),
    "clinic": ("amenity", "clinic"),
    "doctor": ("amenity", "doctors"),
    "pharmacy": ("amenity", "pharmacy"),
    "gym": ("leisure", "fitness_centre"),
    "school": ("amenity", "school"),
    "bank": ("amenity", "bank"),
    "atm": ("amenity", "atm"),
    "fuel": ("amenity", "fuel"),
    "car rental": ("amenity", "car_rental"),
    "car repair": ("shop", "car_repair"),
    "plumber": ("craft", "plumber"),
    "electrician": ("craft", "electrician"),
    "salon": ("shop", "hairdresser"),
    "barber": ("shop", "barber"),
    "supermarket": ("shop", "supermarket"),
    "bakery": ("shop", "bakery"),
    "travel": ("office", "travel_agent"),
    "laundry": ("shop", "laundry"),
    "lawyer": ("office", "lawyer"),
    "accountant": ("office", "accountant"),
    "insurance": ("office", "insurance"),
    "notary": ("office", "notary"),
    "engineer": ("office", "engineer"),
    "it": ("office", "it"),
    "telecom": ("shop", "mobile_phone"),
    "architect": ("office", "architect"),
    "photo": ("craft", "photographer"),
    "pet": ("amenity", "veterinary"),
    "library": ("amenity", "library"),
    "park": ("leisure", "park"),
}
MAX_PHOTON_KM = float(os.environ.get("MAX_PHOTON_KM", "120"))


class PhotonScraper(BaseScraper):
    source = "photon"
    ENDPOINT = "https://photon.komoot.io/api/"

    def _location_center(self, query, location):
        search = (location or "").strip() or (query or "").strip()
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": search, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 403:
            return None
        r.raise_for_status()
        items = r.json() or []
        if not items:
            return None
        return float(items[0]["lat"]), float(items[0]["lon"])

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
        lowered = q.lower()
        for key, tag in PHOTON_TAG_MAP.items():
            if key.replace(" ", "") in lowered.replace(" ", ""):
                return tag
        return None

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
            text = json.dumps(obj, ensure_ascii=False)
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


def _haversine(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt

    rlat1, rlon1, rlat2, rlon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


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


def search_all(query, location, limit=20, sources=None, phone_only=False):
    query = (query or "").strip()
    location = (location or "").strip()
    limit = max(1, min(int(limit or 20), 50))
    requested = [s.strip().lower() for s in (sources or "").split(",") if s.strip()]
    if not requested or requested == ["auto"]:
        requested = ["openstreetmap", "photon"]

    scrapers = {
        "openstreetmap": OSMScraper(),
        "photon": PhotonScraper(),
        "google_maps": GoogleMapsScraper(),
    }
    by_source = {k: {"status": "ok", "error": None, "service": k} for k in requested}

    all_businesses = []
    for name in requested:
        scraper = scrapers.get(name)
        if scraper is None:
            by_source[name] = {"status": "error", "error": "unknown source", "service": name}
            continue
        try:
            items = scraper.scrape(query, location, limit)
            if phone_only:
                items = [b for b in items if b.phone]
            all_businesses.extend(items)
        except Exception as exc:
            by_source[name] = {"status": "error", "error": str(exc)[:300], "service": name}

    merged = dedupe(all_businesses)
    return merged[:limit], by_source