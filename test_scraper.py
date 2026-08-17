import asyncio
import json
import os
import re
import unittest
from unittest import mock

import scraper
from cachetools import TTLCache
from scraper import Business, OSMScraper, PhotonScraper, WebsitePhoneEnricher, dedupe


class TestCleanPhone(unittest.TestCase):
    def test_variants(self):
        for raw, want in [
            ("+92 (300) 123-4567", "+923001234567"),
            ("0300-1234567", "03001234567"),
            ("+1 (212) 490-6650", "+12124906650"),
            ("212-490-6650", "2124906650"),
            ("+44 20 7946 0958", "+442079460958"),
        ]:
            self.assertEqual(scraper._clean_phone(raw), want)

    def test_invalid(self):
        for raw in [None, "", "abc", "12345", "+923001" * 5 + "00"]:
            self.assertIsNone(scraper._clean_phone(raw))


class TestExtractPhone(unittest.TestCase):
    def test_tel_link(self):
        html = '<a href="tel:+14155551234">Call us</a>'
        self.assertEqual(scraper.extract_phone_from_html(html), "+14155551234")

    def test_itemprop(self):
        html = '<span itemprop="telephone">(123) 456-7890</span>'
        self.assertEqual(scraper.extract_phone_from_html(html), "1234567890")

    def test_jsonld(self):
        html = '<script type="application/ld+json">{"telephone":"+49 30 12345678"}</script>'
        self.assertEqual(scraper.extract_phone_from_html(html), "+493012345678")

    def test_body_regex(self):
        html = "<html><body><p>Reach us anytime at +91 98765 43210 today.</p></body></html>"
        self.assertEqual(scraper.extract_phone_from_html(html), "+919876543210")

    def test_empty(self):
        self.assertIsNone(scraper.extract_phone_from_html(None))
        self.assertIsNone(scraper.extract_phone_from_html("<html><p>no phone here</p></html>"))

    def test_date_like_skipped(self):
        html = "<html><body><p>Published 2025-01-01, reach us at +49 30 1234567 today.</p></body></html>"
        self.assertEqual(scraper.extract_phone_from_html(html), "+49301234567")


class TestExtractEmails(unittest.TestCase):
    def test_mailto_link(self):
        html = '<a href="mailto:info@acme.com">Email us</a>'
        self.assertEqual(scraper.extract_emails_from_html(html), ["info@acme.com"])

    def test_meta_and_itemprop(self):
        html = '<meta name="email" content="sales@shop.io"><span itemprop="email">billing@shop.io</span>'
        emails = scraper.extract_emails_from_html(html)
        self.assertIn("sales@shop.io", emails)
        self.assertIn("billing@shop.io", emails)

    def test_jsonld(self):
        html = '<script type="application/ld+json">{"email":"contact@law.com"}</script>'
        self.assertEqual(scraper.extract_emails_from_html(html), ["contact@law.com"])

    def test_body_text_regex(self):
        html = "<html><body><p>Write to hello@mailbox.co.uk for quotes.</p></body></html>"
        self.assertEqual(scraper.extract_emails_from_html(html), ["hello@mailbox.co.uk"])

    def test_filters_images_and_example(self):
        html = '<a href="mailto:a@x.com"></a><img src="x"><p>noreply@example.com x.png</p>'
        emails = scraper.extract_emails_from_html(html)
        self.assertIn("a@x.com", emails)
        self.assertFalse(any(e in ("noreply@example.com",) for e in emails))

    def test_empty(self):
        self.assertEqual(scraper.extract_emails_from_html(None), [])
        self.assertEqual(scraper.extract_emails_from_html("<p>no email here</p>"), [])

    def test_limit(self):
        html = "<p>" + " ".join(f"user{i}@mail.com" for i in range(6)) + "</p>"
        self.assertEqual(len(scraper.extract_emails_from_html(html, limit=2)), 2)


class TestDedupe(unittest.TestCase):
    def test_dedupe(self):
        a = Business(name="Cafe X", address="1 Main St")
        b = Business(name="cafe  x", address="1main st")  # same normalized
        c = Business(name="Cafe X", address="2 Main St")  # different address
        out = dedupe([a, b, c])
        self.assertEqual(len(out), 2)


class TestOsmQuery(unittest.TestCase):
    def setUp(self):
        self.scraper = OSMScraper()
        patcher = mock.patch.object(self.scraper, "_resolve_bbox", return_value=[1, 2, 3, 4])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tag_rule(self):
        q = self.scraper._build_query("Restaurant", "Anywhere", 20)
        self.assertIn('node["amenity"="restaurant"]', q)

    def test_regex_rule(self):
        q = self.scraper._build_query("RealEstate", "Karachi", 20)
        self.assertIn('node["office"~"estate|real_estate"]', q)

    def test_fallback_ci(self):
        q = self.scraper._build_query("acme widgets", "Karachi", 20)
        self.assertIn('node["name"~"acme\\ widgets",i]', q)

    def test_hospital_rule(self):
        q = self.scraper._build_query("Hospital", "London", 20)
        self.assertIn('node["amenity"="hospital"]', q)

    def test_property_management_precedence(self):
        q = self.scraper._build_query("property management", "London", 20)
        self.assertIn('node["office"="property_management"]', q)

    def test_roofing_rule(self):
        q = self.scraper._build_query("Roofer", "London", 20)
        self.assertIn('node["craft"="roofer"]', q)

    def test_shoe_maker_matches_footwear_rule(self):
        q = self.scraper._build_query("Shoe maker", "Karachi", 20)
        self.assertIn('node["shop"="shoes"]', q)

    def test_shoe_store_matches_footwear_rule(self):
        q = self.scraper._build_query("shoe store", "Karachi", 20)
        self.assertIn('node["shop"="shoes"]', q)

    def test_mapped_tag_longest_match(self):
        self.assertEqual(PhotonScraper._mapped_tag("Parking"), ("amenity", "parking"))
        self.assertEqual(PhotonScraper._mapped_tag("Park"), ("leisure", "park"))
        self.assertEqual(PhotonScraper._mapped_tag("Hospital"), ("amenity", "hospital"))
        self.assertEqual(PhotonScraper._mapped_tag("shoe maker"), ("shop", "shoes"))
        self.assertEqual(PhotonScraper._mapped_tag("Shoes"), ("shop", "shoes"))
        self.assertIsNone(PhotonScraper._mapped_tag("software"))

    def test_unknown_source(self):
        from scraper import search_all
        with mock.patch.object(OSMScraper, "scrape", return_value=[]), mock.patch.object(
            PhotonScraper, "scrape", return_value=[]
        ), mock.patch.object(WebsitePhoneEnricher, "enrich", return_value=[]):
            results, by_source, enriched = search_all("restaurant", "Karachi", sources="bogus")
        self.assertEqual(by_source["bogus"]["status"], "error")
        self.assertEqual(len(results), 0)
        self.assertEqual(enriched, 0)


class TestEnricher(unittest.TestCase):
    def test_enrich_sets_phone(self):
        b = Business(name="Site Co", website="https://example.com")
        e = WebsitePhoneEnricher()
        with mock.patch.object(e, "_fetch", return_value='<a href="tel:+15105551234">x</a>'):
            e.enrich([b], max_sites=5)
        self.assertEqual(b.phone, "+15105551234")
        self.assertEqual(b.extra.get("phone_via"), "website")

    def test_enrich_sets_email(self):
        b = Business(name="Mail Co", website="https://mailer.example")
        e = WebsitePhoneEnricher()
        with mock.patch.object(e, "_fetch", return_value='<a href="mailto:hello@mailer.example">hi</a>'):
            e.enrich([b], max_sites=5)
        self.assertEqual(b.extra.get("email"), ["hello@mailer.example"])

    def test_social_sites_skipped(self):
        b = Business(name="Fb Co", website="https://facebook.com/foo")
        e = WebsitePhoneEnricher()
        with mock.patch.object(e, "_fetch", return_value="<p>+1555555</p>"):
            e.enrich([b], max_sites=5)
        self.assertIsNone(b.phone)


class FakeNoDb:
    configured = False

    def cache_get(self, key):
        return None

    def cache_set(self, *a, **k):
        pass

    def insert_leads(self, *a, **k):
        return 0

    def recent_leads(self, *a, **k):
        return []

    def db_status(self):
        return {"configured": False, "status": "not configured"}


class TestApp(unittest.TestCase):
    def test_scrape_payload(self):
        import app

        sample = Business(name="Grand", phone="2124906650", address="NYC", source="photon")
        with mock.patch.object(
            app, "search_all", return_value=([sample], {"photon": {"status": "ok"}}, 0)
        ), mock.patch.object(app, "db", FakeNoDb()), mock.patch.object(
            app, "CACHE", TTLCache(maxsize=8, ttl=60)
        ):
            payload = app.scrape(
                query="restaurant", location="New York", limit=10,
                sources="auto", phone_only=False, enrich=True,
            )
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["results"][0]["name"], "Grand")
            payload2 = app.scrape(
                query="restaurant", location="New York", limit=10,
                sources="auto", phone_only=False, enrich=True,
            )
            self.assertEqual(payload2["count"], 1)
            self.assertEqual(app.search_all.call_count, 1)

    def test_rate_limiter_enforces(self):
        import app

        app.RATE_LIMIT_PER_IP = 2
        app.RATE_LIMIT_WINDOW = 60
        self.addCleanup(lambda: setattr(app, "RATE_LIMIT_PER_IP", 30))
        app._RATE_HITS.clear()

        class FakeHeaders:
            def get(self, _k, _d=None):
                return "9.9.9.9"

        class FakeURL:
            path = "/scrape"

        class FakeRequest:
            headers = FakeHeaders()
            client = None
            url = FakeURL()

        sentinel = {"ok": True}
        async def call_next(req):
            return sentinel

        async def run():
            r1 = await app.rate_limit_middleware(FakeRequest(), call_next)
            r2 = await app.rate_limit_middleware(FakeRequest(), call_next)
            r3 = await app.rate_limit_middleware(FakeRequest(), call_next)
            return r1, r2, r3

        r1, r2, r3 = asyncio.run(run())
        self.assertEqual(r1, sentinel)
        self.assertEqual(r2, sentinel)
        self.assertEqual(r3.status_code, 429)

    def test_health_exempt_from_rate_limit(self):
        import app

        app.RATE_LIMIT_PER_IP = 1
        self.addCleanup(lambda: setattr(app, "RATE_LIMIT_PER_IP", 30))
        app._RATE_HITS.clear()

        class FakeHeaders:
            def get(self, _k, _d=None):
                return "8.8.8.8"

        class FakeURL:
            path = "/health"

        class FakeRequest:
            headers = FakeHeaders()
            client = None
            url = FakeURL()

        async def call_next(req):
            return {"ok": True}

        one = asyncio.run(app.rate_limit_middleware(FakeRequest(), call_next))
        two = asyncio.run(app.rate_limit_middleware(FakeRequest(), call_next))
        self.assertEqual(one, {"ok": True})
        self.assertEqual(two, {"ok": True})


class TestCategories(unittest.TestCase):
    def test_categories_endpoint(self):
        import app

        cats = app.categories()
        names = [c["name"] for c in cats["categories"]]
        self.assertIn("real estate", names)
        self.assertIn("hospital", names)
        self.assertIn("roofing", names)
        for expected in ("auto parts", "chiropractor", "glazier", "handyman", "cinema", "marina"):
            self.assertIn(expected, names)

    def test_new_rules_map_photon(self):
        pairs = [
            ("auto parts", ("shop", "car_parts")),
            ("chiropractor", ("healthcare", "chiropractor")),
            ("glazier", ("craft", "glazier")),
            ("handyman", ("craft", "handyman")),
            ("cinema", ("amenity", "cinema")),
            ("marina", ("leisure", "marina")),
        ]
        for name, want in pairs:
            self.assertEqual(scraper.PHOTON_TAG_MAP.get(name), want, name)

    def test_rule_hit_priority_nail_before_salon(self):
        names = [n for n, _, _ in scraper.TAG_RULES]
        self.assertLess(names.index("nail salon"), names.index("salon"))
        for name, pattern, filters in scraper.TAG_RULES:
            if re.search(pattern, "nail salon", re.IGNORECASE):
                self.assertEqual(name, "nail salon")
                self.assertIn("shop=beauty", filters)
                break
        else:
            self.fail("no rule matched 'nail salon'")

    def test_photon_longest_match(self):
        b = PhotonScraper()
        # "hospital" must map to amenity=hospital, not the shorter "it" office key
        self.assertEqual(b._mapped_tag("hospital"), ("amenity", "hospital"))
        self.assertEqual(b._mapped_tag("auto parts"), ("shop", "car_parts"))
        self.assertEqual(b._mapped_tag("unknown thing xyz"), None)

    def test_build_csv(self):
        import app

        b = Business(name="Grand", phone="2124906650", address="NYC", source="photon",
                     extra={"phone_via": "website", "email": ["hi@grand.example"]})
        text = app._build_csv([b])
        self.assertIn("name,phone,email,address", text)
        self.assertIn("Grand,2124906650,hi@grand.example,NYC", text)
        self.assertIn(",website", text)


class TestSearchAllClamp(unittest.TestCase):
    def test_max_results_env_clamps(self):
        items = [
            Business(name=f"X {i}", address=f"{i} Street") for i in range(5)
        ]
        with mock.patch.object(scraper, "MAX_RESULTS", 3), mock.patch.object(
            OSMScraper, "scrape", return_value=items
        ), mock.patch.object(PhotonScraper, "scrape", return_value=items):
            results, _, enriched = scraper.search_all(
                "restaurant", "Karachi", limit=999, sources="openstreetmap,photon",
                enrich=False,
            )
        self.assertEqual(len(results), 3)
        self.assertEqual(enriched, 0)

    def test_max_results_default(self):
        self.assertEqual(scraper.MAX_RESULTS, 50)


class TestHealthProbe(unittest.TestCase):
    def test_health_probe_degraded_on_empty(self):
        import app

        class FakePhoton:
            def scrape(self, *a, **k):
                return []

        class FakeOSM:
            def scrape(self, *a, **k):
                return []

        with mock.patch.object(app, "PhotonScraper", FakePhoton), mock.patch.object(
            app, "OSMScraper", FakeOSM
        ):
            out = app.health(probe=True)
        self.assertEqual(out["probe"], True)
        self.assertEqual(out["sources"]["photon"], "empty")
        self.assertEqual(out["status"], "degraded")

    def test_health_plain(self):
        import app

        out = app.health(probe=False)
        self.assertEqual(out["status"], "ok")
        self.assertFalse(out["probe"])
        self.assertIn("database", out)


class TestDbDegradation(unittest.TestCase):
    def test_no_db_noops(self):
        db = __import__("db", fromlist=["db"])
        with mock.patch.object(db, "configured", False):
            self.assertIsNone(db.cache_get("k"))
            db.cache_set("k", {"a": 1})
            self.assertEqual(db.insert_leads("q", "l", []), 0)
            self.assertEqual(db.recent_leads(), [])
            status = db.db_status()
            self.assertFalse(status["configured"])

    def test_configured_true_without_psycopg_falls_back(self):
        db = __import__("db", fromlist=["db"])
        with mock.patch.object(db, "configured", True), mock.patch.object(
            db, "_psycopg", None
        ):
            self.assertIsNone(db.cache_get("k"))
            status = db.db_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["status"], "error")


class TestDbWiring(unittest.TestCase):
    def test_scrape_persists_to_db_and_seeds_memory(self):
        import app

        sample = Business(name="Grand", phone="2124906650", address="NYC", source="photon")

        class FakeDb:
            configured = True
            calls = {"set": [], "insert": [], "get": []}

            def cache_get(self, key):
                self.calls["get"].append(key)
                return None

            def cache_set(self, key, payload, ttl=600):
                self.calls["set"].append(key)

            def insert_leads(self, q, loc, businesses):
                self.calls["insert"].append((q, loc, len(businesses)))

            def db_status(self):
                return {"configured": True, "status": "ok"}

        fake = FakeDb()
        with mock.patch.object(app, "db", fake), mock.patch.object(
            app, "CACHE", TTLCache(maxsize=8, ttl=60)
        ), mock.patch.object(app, "search_all", return_value=([sample], {"p": {"status": "ok"}}, 0)) as m_search:
            p1 = app.scrape(query="restaurant", location="New York", limit=10,
                            sources="auto", phone_only=False, enrich=True)
            p2 = app.scrape(query="restaurant", location="New York", limit=10,
                            sources="auto", phone_only=False, enrich=True)
            self.assertEqual(p1["count"], 1)
            self.assertEqual(p2, p1)
            self.assertEqual(m_search.call_count, 1)
            self.assertEqual(len(fake.calls["insert"]), 1)
            self.assertEqual(fake.calls["insert"][0][:2], ("restaurant", "New York"))
            self.assertEqual(len(fake.calls["set"]), 1)

    def test_lead_store_endpoint(self):
        import app

        class FakeDb:
            configured = True

            def recent_leads(self, query=None, location=None, limit=20):
                self.calls = (query, location, limit)
                return [{"name": "X", "phone": "1"}]

        fake = FakeDb()
        with mock.patch.object(app, "db", fake), mock.patch.object(app, "LEADS_API_KEY", "sekrit"):
            out = app.lead_store(query="hotel", location="Dubai", limit=5, x_api_key="sekrit")
        self.assertEqual(out["count"], 1)
        self.assertEqual(fake.calls, ("hotel", "Dubai", 5))

    def test_lead_store_rejects_missing_key(self):
        import app

        with mock.patch.object(app, "LEADS_API_KEY", "sekrit"):
            resp = app.lead_store(query="hotel", location="Dubai", limit=5)
        self.assertEqual(resp.status_code, 401)

    def test_lead_store_rejects_wrong_key(self):
        import app

        with mock.patch.object(app, "LEADS_API_KEY", "sekrit"):
            resp = app.lead_store(query="hotel", location="Dubai", limit=5, x_api_key="nope")
        self.assertEqual(resp.status_code, 401)

    def test_lead_store_disabled_when_no_key(self):
        import app

        with mock.patch.object(app, "LEADS_API_KEY", ""):
            resp = app.lead_store(query="hotel", location="Dubai", limit=5)
        self.assertEqual(resp.status_code, 403)


class TestSSRFGuard(unittest.TestCase):
    def test_blocks_internal(self):
        for url in (
            "http://localhost:8080/x",
            "http://127.0.0.1/x",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/x",
            "http://intranet/",
            "ftp://example.com/",
            "http://foo.internal/",
            "https://foo.local/x",
        ):
            self.assertFalse(scraper._is_safe_url(url), url)

    def test_accepts_public(self):
        with mock.patch.object(
            scraper.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            self.assertTrue(scraper._is_safe_url("https://example.com/"))
            self.assertTrue(scraper._is_safe_url("https://www.some-business.co.uk/page"))

    def test_fetch_blocks_internal_redirect(self):
        e = WebsitePhoneEnricher()

        class FakeResp:
            status_code = 302
            headers = {"Location": "http://127.0.0.1/secret"}

            def close(self):
                pass

            def iter_content(self, *a):
                return []

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, *a, **k):
                return FakeResp()

        with mock.patch.object(scraper.requests, "Session", FakeSession):
            self.assertIsNone(e._fetch("https://public.example.com/"))

    def test_fetch_rejects_non_http(self):
        e = WebsitePhoneEnricher()
        with mock.patch.object(scraper, "_is_safe_url", return_value=False):
            self.assertIsNone(e._fetch("file:///etc/passwd"))


class TestLeadpack(unittest.TestCase):
    def test_fetch_uses_custom_base(self):
        import generate_leadpack as g

        class FakeResp:
            def read(self):
                return b'{"results": [], "generated_at": "x"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()) as m:
            data = g.fetch("restaurant", "Karachi", 5, base="https://custom.example:444")
        self.assertEqual(data["results"], [])
        url = m.call_args.args[0].full_url
        self.assertTrue(url.startswith("https://custom.example:444/scrape?"), url)

    def _rows(self, count, phones):
        rows = []
        for i in range(count):
            has_phone = i < phones
            rows.append(
                {
                    "name": f"Place {i}",
                    "phone": f"+1 555 000 {i:04d}" if has_phone else "",
                    "email": ["x@y.z"] if has_phone else [],
                    "extra": {"phone_via": "osm"} if has_phone else {},
                    "address": "1 Main St",
                    "website": "",
                    "latitude": "1",
                    "longitude": "2",
                    "source": "openstreetmap",
                }
            )
        return rows

    def _fake_resp(self, rows):
        class FakeResp:
            def read(self):
                return json.dumps({"results": rows, "generated_at": "x"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return FakeResp()

    def test_base_prefix(self):
        import generate_leadpack as g

        self.assertEqual(g.base_prefix("austin_dentist-2026-08-16.csv"), "austin_dentist")
        self.assertEqual(g.base_prefix("new_york_restaurant-2026-08-16.csv"), "new_york_restaurant")
        self.assertEqual(g.base_prefix("london_cafe-2026-08-16.csv"), "london_cafe")

    def test_gate_rejects_low_count(self):
        import generate_leadpack as g

        self.assertFalse(g._gate(10, 8, 1)[0])
        self.assertIn("count", g._gate(10, 8, 1)[1])

    def test_gate_rejects_low_contacts(self):
        import generate_leadpack as g

        self.assertFalse(g._gate(40, 1, 0)[0])
        self.assertIn("phone", g._gate(40, 1, 0)[1])

    def test_gate_passes_on_phone_pct_or_emails(self):
        import generate_leadpack as g

        self.assertTrue(g._gate(40, 8, 0)[0])  # 20% phones
        self.assertTrue(g._gate(40, 0, 3)[0])  # enough emails

    def test_write_leadpack_skips_and_keeps_previous(self):
        import datetime
        import generate_leadpack as g

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            today = datetime.date.today().isoformat()
            with mock.patch("generate_leadpack.OUT_DIR", tmp):
                prev = os.path.join(tmp, f"testville_restaurant-2026-08-16.csv")
                with open(prev, "w", newline="", encoding="utf-8-sig") as f:
                    f.write("name,phone\noldrow,\n")
                with mock.patch("urllib.request.urlopen", return_value=self._fake_resp(self._rows(40, 0))):
                    info = g.write_leadpack("restaurant", "Testville", 50)
                self.assertFalse(info["passed"])
                self.assertIsNone(info["path"])
                self.assertTrue(os.path.exists(prev))  # previous pack kept

    def test_write_leadpack_odbl_attribution(self):
        import datetime
        import generate_leadpack as g

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            today = datetime.date.today().isoformat()
            with mock.patch("generate_leadpack.OUT_DIR", tmp):
                with mock.patch("urllib.request.urlopen", return_value=self._fake_resp(self._rows(40, 8))):
                    info = g.write_leadpack("restaurant", "Testville", 50)
                self.assertTrue(info["passed"])
                self.assertEqual(info["rows"], 40)
                path = os.path.join(tmp, f"testville_restaurant-{today}.csv")
                self.assertEqual(info["path"], path)
                with open(path, "r", encoding="utf-8-sig") as f:
                    lines = f.read().splitlines()
                self.assertTrue(lines[0].startswith("# Data © OpenStreetMap contributors (ODbL)"), lines[0])
                self.assertEqual(lines[1], "name,phone,email,address,website,latitude,longitude,source,phone_via")


class TestGeocodeCache(unittest.TestCase):
    def test_cache_hit_avoids_network(self):
        scraper._GEO_CACHE.clear()
        items = [{"lat": "1", "lon": "2", "boundingbox": ["0", "2", "0", "2"]}]
        with mock.patch("scraper.requests.get") as mock_get, mock.patch("scraper.time.sleep") as m_sleep:
            mock_get.return_value = mock.MagicMock(status_code=200, json=lambda: items)
            first = scraper.geocode("Karachi", limit=6)
            second = scraper.geocode("karachi", limit=6)  # cached
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(first, items)
        self.assertEqual(second, items)


if __name__ == "__main__":
    unittest.main(verbosity=2)