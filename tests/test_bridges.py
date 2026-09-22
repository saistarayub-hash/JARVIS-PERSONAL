"""Unit tests for v6 bridges: home, music, manifest, conversation memory."""
import sys
import unittest

sys.path.insert(0, ".")


class TestHomeBridge(unittest.TestCase):
    def _home(self):
        from jarvis.brain.home import HomeBridge
        return HomeBridge({}, demo=True, broadcast=lambda p: None)

    def test_light_lifecycle(self):
        h = self._home()
        r = h.light("kitchen", True, 60)
        self.assertTrue(r["ok"] and r["simulated"])
        st = h.state()
        self.assertTrue(st["lights"]["kitchen"]["on"])
        self.assertEqual(st["lights"]["kitchen"]["brightness"], 60)
        h.light("kitchen", False)
        self.assertFalse(h.state()["lights"]["kitchen"]["on"])

    def test_all_lights_and_unknown(self):
        h = self._home()
        h.light("all", False)
        self.assertFalse(any(l["on"] for l in h.state()["lights"].values()))
        bad = h.light("attic", True)
        self.assertFalse(bad["ok"])
        self.assertIn("No light called 'attic'", bad["message"])

    def test_tv_and_climate_clamped(self):
        h = self._home()
        h.tv(True)
        self.assertTrue(h.state()["tv"]["on"])
        r = h.climate(99)
        self.assertEqual(r["target"], 30)
        r = h.climate(2)
        self.assertEqual(r["target"], 16)


class TestMusicBridge(unittest.TestCase):
    def _music(self):
        from jarvis.brain.music import MusicBridge
        return MusicBridge(demo=True, broadcast=lambda p: None)

    def test_play_pause_next(self):
        m = self._music()
        first = m.play("focus")
        self.assertTrue(first["ok"] and first["simulated"])
        self.assertTrue(m.status()["playing"])
        m.pause()
        self.assertFalse(m.status()["playing"])
        nxt = m.next()
        self.assertNotEqual(nxt.get("playing"), first.get("playing"))

    def test_volume_clamped(self):
        m = self._music()
        self.assertEqual(m.volume(140)["volume"], 100)
        self.assertEqual(m.volume(-5)["volume"], 0)


class TestManifestAndConvo(unittest.TestCase):
    def test_manifest_groups(self):
        from jarvis.brain.llm import capability_manifest
        m = capability_manifest()
        for grp in ("Smart home", "Music", "Scenes & routines", "Markets"):
            self.assertIn(grp, m)
        self.assertIn("home_light", m)
        self.assertIn("analyze_screen", m)

    def test_convo_roundtrip(self):
        import os
        import tempfile
        from jarvis.brain.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            mem = Memory(os.path.join(d, "m.db"))
            mem.log_convo("user", "play some jazz")
            mem.log_convo("assistant", "Playing jazz, sir.")
            tail = mem.convo_tail(4)
            self.assertEqual([t["role"] for t in tail], ["user", "assistant"])
            self.assertEqual(tail[1]["content"], "Playing jazz, sir.")

    def test_vision_payload_absent_brain(self):
        """see() without fleet/brain must fail politely, not crash."""
        import os
        import tempfile
        from jarvis.config import load_config
        from jarvis.main import Jarvis
        cfg = load_config("config.yaml")
        cfg["root"] = tempfile.mkdtemp()
        cfg.setdefault("fleet", {})["enabled"] = False
        j = Jarvis(cfg)
        r = j.see("web-01")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
