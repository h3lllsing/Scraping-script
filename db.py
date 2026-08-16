import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("db")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
configured = bool(DATABASE_URL)

_psycopg = None
if configured:
    try:
        import psycopg2
        import psycopg2.extras

        _psycopg = psycopg2
    except Exception as exc:  # pragma: no cover
        logger.error("DATABASE_URL set but psycopg2 unavailable: %s", exc)
        configured = False

_lock = threading.Lock()
_conn = None
_last_err = None
_db_ready = False


class DbError(Exception):
    pass


def _get_conn():
    global _conn, _last_err, _db_ready
    if not configured:
        raise DbError("database not configured")
    if _conn is not None:
        try:
            with _conn.cursor() as cur:
                cur.execute("SELECT 1")
            return _conn
        except Exception:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
    try:
        _conn = _psycopg.connect(DATABASE_URL, connect_timeout=10, sslmode="require")
        _last_err = None
        _db_ready = True
        return _conn
    except Exception as exc:
        _last_err = str(exc)[:300]
        logger.warning("db connect failed: %s", _last_err)
        raise DbError(_last_err)


def init_db():
    """Create tables/indexes if the database is configured."""
    if not configured:
        return False
    with _lock:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scrape_cache (
                    cache_key  text PRIMARY KEY,
                    payload    jsonb NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    expires_at timestamptz NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id          bigserial PRIMARY KEY,
                    query       text NOT NULL,
                    location    text NOT NULL DEFAULT '',
                    source      text,
                    name        text,
                    phone       text,
                    email       text,
                    address     text,
                    website     text,
                    latitude    double precision,
                    longitude   double precision,
                    extra       jsonb,
                    captured_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS leads_uniq
                ON leads (query, coalesce(lower(name), ''), coalesce(lower(address), ''))
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS leads_query_loc ON leads (query, location)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS leads_captured ON leads (captured_at)")
            conn.commit()
    return True


def cache_get(key):
    if not configured:
        return None
    try:
        with _lock:
            conn = _get_conn()
            with conn.cursor(cursor_factory=_psycopg.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT payload FROM scrape_cache WHERE cache_key = %s AND expires_at > now()",
                    (str(key),),
                )
                row = cur.fetchone()
        return row["payload"] if row else None
    except Exception as exc:
        logger.warning("cache_get failed: %s", exc)
        return None


def cache_set(key, payload, ttl=600):
    if not configured:
        return
    try:
        with _lock:
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scrape_cache (cache_key, payload, expires_at)
                    VALUES (%s, %s::jsonb, %s)
                    ON CONFLICT (cache_key) DO UPDATE
                    SET payload = EXCLUDED.payload, expires_at = EXCLUDED.expires_at,
                        created_at = now()
                    """,
                    (
                        str(key),
                        json.dumps(payload),
                        datetime.now(timezone.utc) + timedelta(seconds=ttl),
                    ),
                )
                conn.commit()
    except Exception as exc:
        logger.warning("cache_set failed: %s", exc)


def insert_leads(query, location, businesses):
    """Insert scraped businesses into the leads table (dedup by query+name+address)."""
    if not configured or not businesses:
        return 0
    rows = []
    for b in businesses:
        if not getattr(b, "name", None):
            continue
        d = b.as_dict()
        extra = d.get("extra") or {}
        emails = extra.get("email") or []
        rows.append(
            (
                query,
                location,
                d.get("source"),
                d.get("name"),
                d.get("phone"),
                "; ".join(emails) if isinstance(emails, list) else emails,
                d.get("address"),
                d.get("website"),
                d.get("latitude"),
                d.get("longitude"),
                json.dumps(extra),
            )
        )
    if not rows:
        return 0
    try:
        with _lock:
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO leads
                        (query, location, source, name, phone, email, address, website,
                         latitude, longitude, extra)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                )
                conn.commit()
            return cur.rowcount
    except Exception as exc:
        logger.warning("insert_leads failed: %s", exc)
        return 0


def recent_leads(query=None, location=None, limit=20):
    if not configured:
        return []
    try:
        with _lock:
            conn = _get_conn()
            with conn.cursor(cursor_factory=_psycopg.extras.DictCursor) as cur:
                where, params = [], []
                if query:
                    params.append(query.lower())
                    where.append("lower(query) = %s")
                if location:
                    params.append(location.lower())
                    where.append("lower(location) = %s")
                sql = "SELECT * FROM leads"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY captured_at DESC LIMIT %s" % int(limit)
                cur.execute(sql, params)
                rows = cur.fetchall()
        out = []
        for r in rows:
            row = dict(r)
            extra = row.pop("extra", None) or {}
            rec = {k: row[k] for k in ("name", "phone", "email", "address", "website",
                                       "latitude", "longitude", "source", "captured_at")}
            rec["extra"] = json.loads(extra) if isinstance(extra, str) else extra
            out.append(rec)
        return out
    except Exception as exc:
        logger.warning("recent_leads failed: %s", exc)
        return []


def db_status():
    if not configured:
        return {"configured": False, "status": "not configured"}
    try:
        st = int(time.time())
        with _lock:
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM scrape_cache")
                cached = cur.fetchone()[0]
        return {
            "configured": True,
            "status": "ok",
            "latency_ms": int((time.time() - st) * 1000),
            "cache_rows": cached,
        }
    except Exception as exc:
        return {"configured": True, "status": "error", "error": str(exc)[:200]}


def close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None