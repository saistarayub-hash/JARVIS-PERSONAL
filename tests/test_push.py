"""Unit tests for v9: push bridge honesty, overnight digest, browser engine.

Everything here runs offline — the whole point of v9's design is that without
credentials nothing leaves the machine, and this sandbox proves it by having
no internet at all.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from jarvis.brain.memory import Memory
from jarvis.brain.push import PushBridge
from jarvis.brain.browser import BrowserEngine


def _mem():
    return Memory(os.path.join(tempfile.mkdtemp(), "m.db"))


class TestPushHonesty(unittest.TestCase):
    def test_no_credentials_is_simulated_outbox(self):
        m = _mem()
        pb = PushBridge({}, memory=m)
        res = pb.send("hello world")
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["simulated"])
        self.assertIn("no credentials", res[0]["status"])
        # never silent: it lands in the outbox log
        log = m.push_recent()
        self.assertEqual(log[0]["text"], "hello world")
        self.assertEqual(log[0]["status"], "no credentials — kept in outbox, not sent")

    def test_route_respects_mode_and_config(self):
        pb = PushBridge({"mode": "off"}, memory=_mem())
        self.assertEqual(pb.route("alert!", alert=True), [])
        pb = PushBridge({"mode": "alerts"}, memory=_mem())
        self.assertEqual(pb.route("note", alert=False), [])   # no channels configured
        pb = PushBridge({"mode": "all"}, memory=_mem())
        self.assertEqual(pb.route("note"), [])                # still nothing configured

    def test_env_credentials_count_as_configured(self):
        os.environ["JARVIS_TELEGRAM_TOKEN"] = "t"
        os.environ["JARVIS_TELEGRAM_CHAT"] = "c"
        try:
            pb = PushBridge({}, memory=_mem())
            self.assertTrue(pb.status()["telegram"])
            self.assertEqual(pb.configured_channels(), ["telegram"])
        finally:
            del os.environ["JARVIS_TELEGRAM_TOKEN"], os.environ["JARVIS_TELEGRAM_CHAT"]

    def test_configured_but_unreachable_fails_honestly(self):
        # Real channel wiring, but sandbox has no internet: must come back
        # as a *failure*, never as a fake success and never as "simulated".
        m = _mem()
        pb = PushBridge({"mode": "all",
                         "telegram": {"bot_token": "1:fake", "chat_id": "9"}},
                        memory=m)
        res = pb.send("x", ["telegram"])
        self.assertFalse(res[0]["simulated"])
        self.assertNotEqual(res[0]["status"], "sent")
        self.assertIn("failed", res[0]["status"])

    def test_status_shape(self):
        pb = PushBridge({"mode": "all"})
        st = pb.status()
        self.assertEqual(st["mode"], "all")
        self.assertFalse(st["telegram"])
        self.assertFalse(st["mail"])


class TestDigest(unittest.TestCase):
    def setUp(self):
        from jarvis.config import load_config
        from jarvis.main import Jarvis
        self.root = tempfile.mkdtemp()
        cfg = load_config("config.yaml")
        cfg["demo"] = True
        cfg["root"] = self.root
        cfg["llm"]["provider"] = "none"
        cfg["voice"]["enabled"] = False
        cfg["digest"] = {"enabled": True, "quiet_hours": [0, 24]}
        self.j = Jarvis(cfg)

    def _jarvis_with_window(self, hours):
        self.j.cfg["digest"] = {"enabled": True, "quiet_hours": hours}

    def test_alert_stashed_in_window(self):
        self._jarvis_with_window([0, 24])
        self.assertTrue(self.j._digest_window())
        self.j.announce({"type": "alert", "text": "rand crossed 19"})
        self.assertEqual(self.j.memory.digest_pending_count(), 1)

    def test_report_lists_and_clears(self):
        self._jarvis_with_window([0, 24])
        self.j.announce({"type": "alert", "text": "page changed"})
        report = self.j.digest_report()
        self.assertIn("page changed", report)
        self.assertIn("1 item", report)
        self.assertEqual(self.j.memory.digest_pending_count(), 0)
        self.assertIn("quiet night", self.j.digest_report())

    def test_disabled_window_passes_through(self):
        self._jarvis_with_window([])
        self.j.cfg["digest"] = {"enabled": False, "quiet_hours": [0, 24]}
        self.assertFalse(self.j._digest_window())
        self.j.announce({"type": "alert", "text": "now"})
        self.assertEqual(self.j.memory.digest_pending_count(), 0)

    def test_handle_digest_intent(self):
        out = self.j.handle("what did I miss")
        self.assertIn("quiet night", out["reply"])


class TestBrowser(unittest.TestCase):
    def test_unavailable_is_stated_not_faked(self):
        b = BrowserEngine({"enabled": True}, root=tempfile.mkdtemp())
        av = b.available()
        self.assertFalse(av["ok"])
        self.assertTrue(av["reason"])          # must say WHY, not shrug

    def test_disabled_by_config(self):
        b = BrowserEngine({"enabled": False})
        self.assertIn("disabled", b.available()["reason"])

    def test_open_page_degrades_to_labelled_text(self):
        # nothing listening on port 9: fallback fetch must fail honestly too
        b = BrowserEngine({"enabled": True}, root=tempfile.mkdtemp())
        res = b.open_page("http://127.0.0.1:9/nope")
        self.assertFalse(res["ok"])
        self.assertIn("reason", res)

    def test_engine_never_raises_for_bad_urls(self):
        b = BrowserEngine({"enabled": True}, root=tempfile.mkdtemp())
        res = b.open_page("not a real url at all")
        self.assertFalse(res["ok"])


class TestIntents(unittest.TestCase):
    def test_v9_phrases(self):
        from jarvis.brain.rules import _match
        self.assertEqual(_match("render example.com"),
                         ("browser", {"url": "example.com"}))
        self.assertEqual(_match("what did I miss")[0], "digest")
        ps = _match("send dinner plans to telegram")
        self.assertEqual(ps[0], "push_send")
        self.assertEqual(ps[1]["channel"], "telegram")
        self.assertEqual(ps[1]["text"], "dinner plans")

    def test_neighbours_untouched(self):
        from jarvis.brain.rules import _match
        self.assertEqual(_match("read http://x.com")[0], "read")
        self.assertEqual(_match("text sam saying hi")[0], "sms")
        self.assertEqual(_match("open spotify")[0], "open")
        self.assertEqual(_match("watch http://x.com for news every 5 minutes")[0],
                         "webwatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
