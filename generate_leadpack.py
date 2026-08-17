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

QUALITY_MIN_COUNT = int(os.environ.get("QUALITY_MIN_COUNT", "30"))
QUALITY_MIN_PHONE_PCT = int(os.environ.get("QUALITY_MIN_PHONE_PCT", "5"))
QUALITY_MIN_EMAILS = int(os.environ.get("QUALITY_MIN_EMAILS", "2"))

ODBL_LINE = "# Data © OpenStreetMap contributors (ODbL) — https://www.openstreetmap.org/copyright"

PACKS = [
    {"city": "New York", "query": "restaurant", "limit": 50},
    {"city": "New York", "query": "dentist", "limit": 50},
    {"city": "London", "query": "dentist", "limit": 50},
    {"city": "Melbourne", "query": "cafe", "limit": 50},
    {"city": "Auckland", "query": "restaurant", "limit": 50},
]

COLUMNS = [
    "name",
    "phone",
    "email",
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


def fetch(query, city, limit, base=None):
    base = (base or API_BASE).rstrip("/")
    params = {
        "query": query,
        "location": city,
        "limit": limit,
        "enrich": "true",
        "sources": "openstreetmap,photon",
    }
    url = f"{base}/scrape?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "leadpack-generator/1.0"})
    with urllib.request.urlopen(req, timeout=150) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slug(text):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")


def base_prefix(name):
    stem = name[: -len(".csv")]
    return stem.rsplit("-", 3)[0]


def _gate(count, phones, emails):
    if count < QUALITY_MIN_COUNT:
        return False, f"count {count} < {QUALITY_MIN_COUNT}"
    pct = (100 * phones / count) if count else 0
    if pct < QUALITY_MIN_PHONE_PCT and emails < QUALITY_MIN_EMAILS:
        return False, (
            f"phone {pct:.0f}% < {QUALITY_MIN_PHONE_PCT}% and emails {emails} < {QUALITY_MIN_EMAILS}"
        )
    return True, "ok"


def write_leadpack(query, city, limit, base=None):
    data = fetch(query, city, limit, base=base)
    results = data.get("results", []) or []
    for row in results:
        row["phone_via"] = (row.get("extra") or {}).get("phone_via") or ""
        row["email"] = "; ".join((row.get("extra") or {}).get("email") or [])
    results.sort(key=lambda r: (0 if r.get("phone") else 1, (r.get("name") or "").lower()))

    count = len(results)
    phones = sum(1 for r in results if r.get("phone"))
    emails = sum(1 for r in results if r.get("email"))
    passed, reason = _gate(count, phones, emails)
    if not passed:
        return {
            "passed": False,
            "reason": reason,
            "rows": count,
            "phones": phones,
            "emails": emails,
            "path": None,
            "generated": data.get("generated_at"),
        }

    today = datetime.date.today().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)
    prefix = f"{slug(city)}_{slug(query)}"
    path = os.path.join(OUT_DIR, f"{prefix}-{today}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(ODBL_LINE + "\n")
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})
    for name in os.listdir(OUT_DIR):
        if name.startswith(prefix) and name != os.path.basename(path):
            try:
                os.remove(os.path.join(OUT_DIR, name))
            except OSError:
                pass
    return {
        "passed": True,
        "path": path,
        "rows": count,
        "phones": phones,
        "emails": emails,
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

    roster_prefixes = {f"{slug(c)}_{slug(q)}" for q, c, _ in ops}
    if os.path.isdir(OUT_DIR):
        for name in os.listdir(OUT_DIR):
            if not name.endswith(".csv"):
                continue
            if base_prefix(name) not in roster_prefixes:
                try:
                    os.remove(os.path.join(OUT_DIR, name))
                except OSError:
                    pass

    ok = skip = fail = 0
    for i, (q, c, n) in enumerate(ops):
        try:
            info = write_leadpack(q, c, n, base=base)
            if info["passed"]:
                ok += 1
                print(
                    f"OK {q:12s} {c:12s} rows={info['rows']:3d} phones={info['phones']:3d} "
                    f"emails={info['emails']:2d} -> {info['path']}"
                )
            else:
                skip += 1
                print(f"SKIP {q:12s} {c:12s} {info['reason']} (kept previous pack if any)")
        except Exception as exc:
            fail += 1
            print(f"FAIL {q:12s} {c:12s} {str(exc)[:140]}")
        if i < len(ops) - 1:
            time.sleep(2)
    print(f"done: {ok} ok, {skip} skipped (quality), {fail} failed / {len(ops)}")


if __name__ == "__main__":
    main()