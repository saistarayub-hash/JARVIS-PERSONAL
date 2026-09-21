"""Unit tests for the SELF engine: signals, alias mining, routines, tuning."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, ".")

from jarvis.brain.memory import Memory
from jarvis.brain.self import SelfEngine


def _engine(tmp, **scfg):
    mem = Memory(os.path.join(tmp, "m.db"))
    cfg = {"self": {"enabled": True, "tune_every_minutes": 0.01,
                    "alias_min_uses": 2, **scfg}}
    return mem, SelfEngine(mem, cfg, broadcast=lambda p: None)


class TestSignals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem, self.eng = _engine(self.tmp)

    def test_praise_and_correction(self):
        self.eng.on_turn("open vscode", "open", "open_app", "vscode", True, 5)
        self.eng.on_turn("thanks jarvis", "chitchat", "", "", True, 2)
        rows = self.mem.journal_since(0)
        self.assertEqual(rows[0]["signal"], 1)

    def test_repetition_counts_as_correction(self):
        self.eng.on_turn("open vscode", "open", "open_app", "vscode", True, 5)
        self.eng.on_turn("open vscode now", "open", "open_app", "vscode", True, 5)
        rows = self.mem.journal_since(0)
        self.assertEqual(rows[0]["signal"], -1)

    def test_negative_phrase(self):
        self.eng.on_turn("play jazz", "play", "music_control", "jazz", True, 5)
        self.eng.on_turn("no not that, play jazz piano", "play",
                         "music_control", "jazz", True, 5)
        rows = self.mem.journal_since(0)
        self.assertEqual(rows[0]["signal"], -1)


class TestAliasMining(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem, self.eng = _engine(self.tmp)

    def _pair(self, phrase, canon, intent="lights"):
        self.mem.log_journal(phrase, "chitchat", "", "", True, 3)
        self.mem.log_journal(canon, intent, "home_light", "", True, 4)

    def test_alias_learned_after_min_uses(self):
        self._pair("zorblat mode", "lights on kitchen")
        notes = self.eng.tick(force=True)
        self.assertEqual(notes, [])  # once isn't enough
        self._pair("zorblat mode", "lights on kitchen")
        notes = self.eng.tick(force=True)
        self.assertEqual(len(notes), 1)
        self.assertIn("taught myself", notes[0])
        rule = self.mem.self_rule_for("zorblat mode")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["canon"], "lights on kitchen")

    def test_alias_not_learned_from_error_followups(self):
        self.mem.log_journal("flarb", "chitchat", "", "", True, 3)
        self.mem.log_journal("glitched", "error", "error", "", False, 3)
        self.mem.log_journal("flarb", "chitchat", "", "", True, 3)
        self.mem.log_journal("glitched", "error", "error", "", False, 3)
        self.assertEqual(self.eng.tick(force=True), [])
        self.assertIsNone(self.mem.self_rule_for("flarb"))


class TestRoutineMining(unittest.TestCase):
    def test_three_days_same_hour_creates_routine(self):
        tmp = tempfile.mkdtemp()
        mem, eng = _engine(tmp, routine_min_days=3)
        base = time.time()
        for day in range(3):
            ts = base - (3 - day) * 86400
            hour_slot = ts - (time.localtime(ts).tm_hour - 9) * 3600 \
                - time.localtime(ts).tm_min * 60
            mem.log_journal("brief me", "brief", "brief", "", True, 9,
                            ts=hour_slot)
        notes = eng.tick(force=True)
        self.assertTrue(any("made that automatic" in n for n in notes), notes)
        self.assertTrue(any(r["name"].startswith("auto-brief")
                            for r in mem.routines_all()))


class TestTuning(unittest.TestCase):
    def test_cooldown_multiplier_rises_with_corrections(self):
        tmp = tempfile.mkdtemp()
        mem, eng = _engine(tmp)
        for i in range(4):
            mem.log_journal(f"thing {i}", "open", "open_app", "x", True, 4)
            mem.set_journal_signal(mem.last_journal()["id"], -1)
        mem.log_journal("nice one", "chitchat", "", "", True, 2)
        mem.set_journal_signal(mem.last_journal()["id"], 1)
        eng.tick(force=True)
        mult = float(mem.tune_get("proactive_cooldown_mult", "1.0"))
        self.assertGreater(mult, 1.0)

    def test_degraded_tool_marked_and_cleared(self):
        tmp = tempfile.mkdtemp()
        mem, eng = _engine(tmp)
        for _ in range(3):
            mem.log_journal("weather", "error", "weather", "", False, 900)
        eng.tick(force=True)
        self.assertTrue(mem.tune_get("degraded:weather"))
        mem.log_journal("weather", "weather", "weather", "", True, 300)
        eng.tick(force=True)
        self.assertEqual(mem.tune_get("degraded:weather"), "")


class TestIntrospection(unittest.TestCase):
    def test_explain_traces_real_decision(self):
        tmp = tempfile.mkdtemp()
        mem, eng = _engine(tmp)
        eng.on_turn("markets", "markets", "market_snapshot", "", True, 12)
        txt = eng.explain()
        self.assertIn("markets", txt)
        self.assertIn("12 ms", txt)

    def test_stats_shape(self):
        tmp = tempfile.mkdtemp()
        mem, eng = _engine(tmp)
        eng.on_turn("hi", "greet", "", "", True, 3)
        st = eng.stats()
        for k in ("turns", "fallback_pct", "praise", "corrections",
                  "self_rules", "tunes"):
            self.assertIn(k, st)


if __name__ == "__main__":
    unittest.main(verbosity=1)
