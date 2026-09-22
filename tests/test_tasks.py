"""Unit tests for v8: task/reminder engine + web watchers."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, ".")

from jarvis.brain.memory import Memory
from jarvis.brain.tasks import TaskEngine, parse_when, split_when
from jarvis.brain.webwatch import WebWatchEngine, _page_text


def _mem():
    return Memory(os.path.join(tempfile.mkdtemp(), "m.db"))


class TestParsing(unittest.TestCase):
    def test_duration(self):
        due, rep = parse_when("in 20 minutes")
        self.assertAlmostEqual(due, time.time() + 1200, delta=5)
        self.assertEqual(rep, "")

    def test_clock_and_tomorrow(self):
        due, _ = parse_when("call the bank at 5 pm")
        self.assertIsNotNone(due)
        due2, rep2 = parse_when("standup every day at 9")
        self.assertEqual(rep2, "daily")
        self.assertIsNotNone(due2)

    def test_split_when(self):
        text, when = split_when("call the bank tomorrow at 9")
        self.assertEqual(text, "call the bank")
        self.assertEqual(when, "tomorrow at 9")
        text2, when2 = split_when("stretch in 20 minutes")
        self.assertEqual(text2, "stretch")
        self.assertEqual(when2, "in 20 minutes")


class TestTaskEngine(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.notes = []
        self.eng = TaskEngine(self.mem, broadcast=lambda p: self.notes.append(p))

    def test_reminder_fires_once(self):
        self.eng.add("stretch legs", "in 0 seconds")
        fired = self.eng.tick()
        self.assertEqual(fired, ["stretch legs"])
        self.assertEqual(self.mem.tasks_open(), [])
        self.assertEqual(self.eng.tick(), [])

    def test_repeat_reschedules(self):
        tid = self.mem.add_task("standup", time.time() - 1, "daily")
        self.eng.tick()
        rows = self.mem.tasks_open()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["due_ts"], time.time() + 80000)

    def test_complete_by_number_and_text(self):
        self.eng.add("email sam")
        self.eng.add("buy milk")
        self.assertIsNotNone(self.eng.complete_and_push("1"))
        self.assertIsNotNone(self.eng.complete_and_push("milk"))
        self.assertEqual(self.mem.tasks_open(), [])


class TestWebWatch(unittest.TestCase):
    PAGE_A = "<html><body><h1>Status: standing by</h1><p>same same</p></body></html>"
    PAGE_B = "<html><body><h1>Status: launching</h1><p>same same</p></body></html>"

    def _engine(self):
        mem = _mem()
        notes = []
        return mem, WebWatchEngine(mem, broadcast=lambda p: notes.append(p),
                                   min_interval_s=0), notes

    def _resp(self, html):
        class R:
            text = html
            status_code = 200
            headers = {}
            def raise_for_status(self): pass
        return R()

    def test_baseline_then_change_alert(self):
        mem, eng, notes = self._engine()
        eng.add("http://x/page", "", 0)
        with mock.patch("requests.get", return_value=self._resp(self.PAGE_A)):
            self.assertEqual(eng.tick(), [])          # baseline
            self.assertEqual(eng.tick(), [])          # unchanged
        with mock.patch("requests.get", return_value=self._resp(self.PAGE_B)):
            out = eng.tick()
        self.assertEqual(len(out), 1)
        self.assertIn("changed", out[0])

    def test_keyword_alert_once(self):
        mem, eng, notes = self._engine()
        eng.add("http://x/page", "launching", 0)
        with mock.patch("requests.get", return_value=self._resp(self.PAGE_A)):
            eng.tick()
            self.assertEqual(eng.tick(), [])
        with mock.patch("requests.get", return_value=self._resp(self.PAGE_B)):
            first = eng.tick()
            second = eng.tick()
        self.assertEqual(len(first), 1)
        self.assertIn("launching", first[0])
        self.assertEqual(second, [])  # no repeat spam

    def test_unreachable_noted_once(self):
        mem, eng, notes = self._engine()
        eng.add("http://x/page", "", 0)
        with mock.patch("requests.get", side_effect=OSError("no net")):
            eng.tick()
            n1 = len(eng.tick())
        self.assertEqual(n1, 0)  # second failure is silent
        w = mem.web_watches()[0]
        self.assertIn("unreachable", w["note"])

    def test_page_text_strips_chrome(self):
        t = _page_text("<html><head><style>x</style></head><body>"
                       "<p>Hello   <b>world</b></p></body></html>")
        self.assertEqual(t, "Hello world")


if __name__ == "__main__":
    unittest.main(verbosity=1)
