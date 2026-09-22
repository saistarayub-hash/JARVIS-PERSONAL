"""Unit tests for the market/news/read parsers, using canned real payloads.

The sandbox has no outbound HTTPS, so provider *parsing* is proven against
recorded response shapes; the live path is exercised on real machines.
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

STOOQ_CSV = ("Symbol,Date,Time,Open,High,Low,Close,Volume\n"
             "eurusd,2026-09-20,16:59:00,1.0830,1.0871,1.0822,1.0856,0\n"
             "usdzar,2026-09-20,16:59:00,18.55,18.70,18.51,18.63,0\n"
             "^spx,2026-09-20,16:59:00,5600.1,5622.0,5590.3,5615.4,0\n")
COINGECKO = {"bitcoin": {"usd": 64210, "usd_24h_change": 1.7},
             "ethereum": {"usd": 3115, "usd_24h_change": -0.8}}
FRANKFURTER = {"base": "EUR", "rates": {"USD": 1.0855, "JPY": 163.2,
                                        "ZAR": 20.21, "GBP": 0.8501}}
ERAPI = {"rates": {"EUR": 0.9212, "ZAR": 18.61, "JPY": 150.3, "GBP": 0.7866}}
RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Markets steady</title><link>https://x/1</link></item>
<item><title>Rand firms</title><link>https://x/2</link></item>
</channel></rss>"""
HTML = b"<html><head><title>Test Page</title></head><body>" \
       b"<script>var x=1;</script><p>Hello   world, this is readable.</p></body></html>"


class FakeResp:
    def __init__(self, text="", content=None, js=None, ctype="text/html"):
        self.text = text
        self.content = content or b""
        self._js = js
        self.headers = {"content-type": ctype}
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


def fake_get_router(routes):
    def fake_get(url, **kw):
        for key, resp in routes.items():
            if key in url:
                return resp
        raise OSError("unroutable in test: " + url)
    return fake_get


class TestProviders(unittest.TestCase):
    def test_stooq_and_coingecko(self):
        from jarvis.brain import fx
        m = fx.Markets({"markets": {}}, demo=False)
        routes = {"stooq.com": FakeResp(text=STOOQ_CSV, ctype="text/csv"),
                  "coingecko": FakeResp(js=COINGECKO, ctype="application/json")}
        with mock.patch("requests.get", side_effect=fake_get_router(routes)):
            snap = m._fetch_real()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["source"], "stooq+coingecko")
        self.assertAlmostEqual(snap["pairs"]["EURUSD"]["price"], 1.0856)
        self.assertAlmostEqual(snap["pairs"]["USDZAR"]["price"], 18.63)
        self.assertIn("S&P 500", snap["indices"])
        self.assertEqual(snap["crypto"]["BTCUSD"]["price"], 64210)
        self.assertAlmostEqual(snap["rates_usd"]["EUR"], 1 / 1.0856, places=6)
        self.assertAlmostEqual(snap["rates_usd"]["ZAR"], 18.63, places=6)

    def test_frankfurter_fallback_and_cross(self):
        from jarvis.brain import fx
        m = fx.Markets({"markets": {}}, demo=False)
        routes = {"frankfurter": FakeResp(js=FRANKFURTER, ctype="application/json"),
                  "coingecko": FakeResp(js={}, ctype="application/json")}
        with mock.patch("requests.get", side_effect=fake_get_router(routes)):
            snap = m._fetch_real()
        self.assertEqual(snap["source"], "frankfurter(ECB daily)")
        self.assertAlmostEqual(snap["pairs"]["EURUSD"]["price"], 1.0855, places=4)
        # USDZAR cross = ZAR-per-USD = 20.21/1.0855
        self.assertAlmostEqual(snap["pairs"]["USDZAR"]["price"],
                               round(20.21 / 1.0855, 5), places=5)

    def test_convert_math(self):
        from jarvis.brain import fx
        m = fx.Markets({"markets": {}}, demo=True)
        routes = {"stooq.com": FakeResp(text=STOOQ_CSV, ctype="text/csv"),
                  "coingecko": FakeResp(js={}, ctype="application/json")}
        with mock.patch("requests.get", side_effect=fake_get_router(routes)):
            m.snapshot(force=True)
        r = m.convert(100, "usd", "zar")
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["value"], 100 * 18.63, places=2)
        r2 = m.convert(100, "zar", "usd")
        self.assertAlmostEqual(r2["value"], 100 / 18.63, places=2)

    def test_news_rss_fallback(self):
        from jarvis.tools import web as wt
        wt.set_demo(False)
        wt._NEWS_CACHE.update(ts=0, items=None)
        routes = {"rss.xml": FakeResp(content=RSS)}

        real_mods = {}
        for name in ("ddgs", "duckduckgo_search"):
            real_mods[name] = sys.modules.get(name, "absent")
            sys.modules[name] = None  # force ImportError path
        real_feeds = wt.DEFAULT_FEEDS
        wt.DEFAULT_FEEDS = ["https://example.com/rss.xml"]
        try:
            with mock.patch("requests.get", side_effect=fake_get_router(routes)):
                out = wt.news("")
            self.assertEqual(out["items"][0]["title"], "Markets steady")
            self.assertFalse(out.get("simulated"))
        finally:
            wt.DEFAULT_FEEDS = real_feeds
            for name, mod in real_mods.items():
                if mod == "absent":
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = mod

    def test_news_demo_feed(self):
        from jarvis.tools import web as wt
        wt.set_demo(True)
        wt._NEWS_CACHE.update(ts=0, items=None)
        with mock.patch("requests.get", side_effect=OSError("no net")):
            out = wt.news("")
        self.assertTrue(out["simulated"])
        self.assertIn("(offline demo feed)", out["items"][0]["title"])
        wt.set_demo(False)

    def test_read_url_html(self):
        from jarvis.tools import web as wt
        with mock.patch("requests.get",
                        return_value=FakeResp(text=HTML.decode(), content=HTML)):
            out = wt.read_url("https://example.com/x")
        self.assertEqual(out["title"], "Test Page")
        self.assertIn("Hello world, this is readable.", out["text"])
        self.assertNotIn("var x", out["text"])

    def test_world_time(self):
        from jarvis.tools import web as wt
        out = wt.world_time("tokyo")
        self.assertIn(":", out["time"])
        out2 = wt.world_time("Johannesburg")
        self.assertEqual(out2["tz"], "Africa/Johannesburg")

    def test_sim_feed_labelled(self):
        from jarvis.brain import fx
        m = fx.Markets({"markets": {}}, demo=True)
        with mock.patch("requests.get", side_effect=OSError("no net")):
            snap = m.snapshot(force=True)
        self.assertTrue(snap["simulated"])
        self.assertIn("EURUSD", snap["pairs"])
        self.assertIn("simulated", snap["source"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
