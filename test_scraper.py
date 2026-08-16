import asyncio
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

    def test_social_sites_skipped(self):
        b = Business(name="Fb Co", website="https://facebook.com/foo")
        e = WebsitePhoneEnricher()
        with mock.patch.object(e, "_fetch", return_value="<p>+1555555</p>"):
            e.enrich([b], max_sites=5)
        self.assertIsNone(b.phone)


class TestApp(unittest.TestCase):
    def test_scrape_payload(self):
        import app

        sample = Business(name="Grand", phone="2124906650", address="NYC", source="photon")
        with mock.patch.object(
            app, "search_all", return_value=([sample], {"photon": {"status": "ok"}}, 0)
        ), mock.patch.object(app, "CACHE", TTLCache(maxsize=8, ttl=60)):
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