import csv
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_BASE = os.environ.get("LEADPACK_API", "https://scraping-script-xi.vercel.app")
OUT_DIR = os.environ.get("LEADPACK_OUT", "docs/leads")
DEFAULT_LIMIT = 50

PACKS = [
    {"city": "Karachi", "query": "RealEstate", "limit": 50},
    {"city": "Karachi", "query": "restaurant", "limit": 50},
    {"city": "Lahore", "query": "RealEstate", "limit": 50},
    {"city": "Lahore", "query": "restaurant", "limit": 50},
    {"city": "Islamabad", "query": "RealEstate", "limit": 50},
    {"city": "Islamabad", "query": "restaurant", "limit": 50},
]

COLUMNS = [
    "name",
    "phone",
    "address",
    "website",
    "latitude",
    "longitude",
    "source",
    "phone_via",
]


def load_packs():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadpacks.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return PACKS


def fetch(query, city, limit):
    params = {
        "query": query,
        "location": city,
        "limit": limit,
        "enrich": "true",
        "sources": "openstreetmap,photon",
    }
    url = f"{API_BASE}/scrape?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "leadpack-generator/1.0"})
    with urllib.request.urlopen(req, timeout=150) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slug(text):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")


def write_leadpack(query, city, limit):
    data = fetch(query, city, limit)
    results = data.get("results", []) or []
    for row in results:
        row["phone_via"] = (row.get("extra") or {}).get("phone_via") or ""
    results.sort(key=lambda r: (0 if r.get("phone") else 1, (r.get("name") or "").lower()))

    today = datetime.date.today().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{slug(city)}_{slug(query)}-{today}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})
    return {
        "path": path,
        "rows": len(results),
        "phones": sum(1 for r in results if r.get("phone")),
        "generated": data.get("generated_at"),
    }


def main():
    args = sys.argv[1:]
    packs = load_packs()
    base = API_BASE

    query = location = limit = None
    all_packs = "--all" in args
    for i, a in enumerate(args):
        if a == "--base" and i + 1 < len(args):
            base = args[i + 1]
        elif a == "--query" and i + 1 < len(args):
            query = args[i + 1]
        elif a == "--location" and i + 1 < len(args):
            location = args[i + 1]
        elif a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        elif a == "--all":
            pass

    ops = []
    if all_packs:
        for p in packs:
            ops.append((p["query"], p["city"], p.get("limit", DEFAULT_LIMIT)))
    elif query and location:
        ops.append((query, location, limit or DEFAULT_LIMIT))
    else:
        print("usage: --all | (--query X --location Y [--limit N]) [--base URL]")
        sys.exit(1)

    today_stamp = datetime.date.today().isoformat()
    if os.path.isdir(OUT_DIR):
        for name in os.listdir(OUT_DIR):
            if name.endswith(".csv") and today_stamp not in name:
                try:
                    os.remove(os.path.join(OUT_DIR, name))
                except OSError:
                    pass

    fail = 0
    for i, (q, c, n) in enumerate(ops):
        try:
            info = write_leadpack(q, c, n)
            print(f"OK {q:12s} {c:12s} rows={info['rows']:3d} phones={info['phones']:3d} -> {info['path']}")
        except Exception as exc:
            fail += 1
            print(f"FAIL {q:12s} {c:12s} {str(exc)[:140]}")
        if i < len(ops) - 1:
            time.sleep(2)
    print(f"done: {len(ops) - fail}/{len(ops)} packs ok")


if __name__ == "__main__":
    main()