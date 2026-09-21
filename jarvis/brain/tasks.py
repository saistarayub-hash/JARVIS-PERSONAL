"""Task & reminder engine: todos, timed reminders, repeating tasks.

Parses natural times ("in 20 minutes", "at 5pm", "tomorrow at 9",
"every day at 8:30", "weekdays at 9"), fires reminders through the same
announce/banner channel as everything else, and reschedules repeats.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, Tuple

_DUR = re.compile(r"\bin\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?)\b")
_REPEAT = re.compile(r"\b(?:every day|daily|weekdays|every weekday)\b", re.I)


def parse_when(phrase: str) -> Tuple[Optional[float], str]:
    """Return (epoch or None, repeat '') from a time phrase inside `phrase`."""
    repeat = ""
    m = _REPEAT.search(phrase)
    if m:
        repeat = "weekdays" if "weekday" in m.group(0).lower() else "daily"
        phrase = phrase.replace(m.group(0), "", 1)
    d = _DUR.search(phrase)
    if d:
        n = int(d.group(1))
        unit = d.group(2).lower()
        secs = n * (60 if unit.startswith(("min",)) else
                    3600 if unit.startswith(("h",)) else 1)
        return time.time() + secs, repeat
    from ..tools.calendar_tools import _parse_when as _pw
    ts = _pw(phrase)
    return ts, repeat


def split_when(phrase: str) -> Tuple[str, str]:
    """Split 'call the bank tomorrow at 9' -> ('call the bank', 'tomorrow at 9')."""
    when: list = []
    p = phrase
    m = _REPEAT.search(p)
    if m:
        when.append(m.group(0).strip())
        p = p.replace(m.group(0), "", 1)
    d = _DUR.search(p)
    if d:
        when.append(d.group(0).strip())
        p = p.replace(d.group(0), "", 1)
    else:
        t = re.search(r"\b(?:at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
                      r"tomorrow(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|"
                      r"today)\b", p, re.I)
        if t:
            when.append(t.group(0).strip())
            p = p.replace(t.group(0), "", 1)
    return re.sub(r"\s+", " ", p).strip(" ,"), " ".join(when)


class TaskEngine:
    def __init__(self, memory, broadcast: Optional[Callable] = None):
        self.memory = memory
        self._broadcast = broadcast or (lambda p: None)

    def add(self, text: str, when_phrase: str = "") -> dict:
        due, repeat = (parse_when(when_phrase) if when_phrase
                       else (None, ""))
        tid = self.memory.add_task(text.strip(), due, repeat)
        self._push()
        label = self._label(due, repeat)
        return {"ok": True, "id": tid, "text": text.strip(),
                "due": due, "repeat": repeat, "label": label}

    @staticmethod
    def _label(due, repeat):
        if due is None:
            return "someday"
        dt = datetime.fromtimestamp(due)
        base = dt.strftime("%H:%M" if dt.date() == datetime.now().date()
                           else "%a %H:%M")
        return base + (f", {repeat}" if repeat else "")

    def tick(self) -> list:
        """Fire anything due; returns the reminders fired."""
        now = time.time()
        fired = []
        for t in self.memory.tasks_open():
            if not t["due_ts"] or t["due_ts"] > now or t["fired"]:
                continue
            if t["repeat"]:
                nxt = t["due_ts"] + 86400
                if t["repeat"] == "weekdays":
                    while datetime.fromtimestamp(nxt).weekday() >= 5:
                        nxt += 86400
                self.memory.reschedule_task(t["id"], nxt, fired=0)
            else:
                self.memory.mark_task_fired(t["id"])
            text = f"Reminder, sir: {t['text']}"
            if t["repeat"]:
                text += f" (repeats {t['repeat']})"
            self._broadcast({"type": "announce", "text": text})
            self._broadcast({"type": "alert",
                             "text": f"⏰ {t['text']} — due now"})
            fired.append(t["text"])
        if fired:
            self._push()
        return fired

    def complete_and_push(self, ident) -> dict | None:
        row = self.memory.complete_task(ident)
        if row:
            self._push()
        return row

    def list_text(self) -> str:
        rows = self.memory.tasks_open()
        if not rows:
            return "Your list is clear, sir."
        bits = []
        for r in rows:
            bits.append(f"{r['id']}) {r['text']} [{self._label(r['due_ts'], r['repeat'])}]")
        return "Open tasks: " + " · ".join(bits) + "."

    def _push(self) -> None:
        self._broadcast({"type": "tasks", "tasks": self.memory.tasks_open()})
