"""Calendar tools for the LLM brain."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from . import tool


def _mem():
    from .memory_tools import get_memory
    mem = get_memory()
    if mem is None:
        raise RuntimeError("Memory not initialised.")
    return mem


def _parse_when(start: str):
    """Accept 'HH:MM', '15:30', '3pm', '3:30 pm', 'tomorrow 9:00', ISO-ish."""
    s = (start or "").strip()
    day = datetime.now()
    if re.search(r"\btomorrow\b", s, re.I):
        day = day + timedelta(days=1)
        s = re.sub(r"\btomorrow\b", "", s, flags=re.I).strip()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        return None
    h = int(m.group(1))
    minute = int(m.group(2) or 0)
    ap = (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or minute > 59:
        return None
    if not re.search(r"\btomorrow\b", (start or ""), re.I) \
            and (h < day.hour or (h == day.hour and minute <= day.minute)):
        day = day + timedelta(days=1)
    return day.replace(hour=h, minute=minute, second=0,
                       microsecond=0).timestamp()


@tool("calendar_today",
      "List the user's calendar events for today / the next 24 hours.", {})
def calendar_today() -> list:
    mem = _mem()
    now = time.time()
    out = []
    for e in mem.calendar_events(now - 3600, now + 86400):
        out.append({"title": e["title"],
                    "start": datetime.fromtimestamp(e["start_ts"]).strftime("%H:%M"),
                    "end": datetime.fromtimestamp(e["end_ts"]).strftime("%H:%M"),
                    "location": e["location"], "url": e["url"]})
    return out


@tool("calendar_add",
      "Add an event. start: 'HH:MM' or '3:30 pm' or 'tomorrow 9:00' "
      "(past times roll to tomorrow).",
      {"title": "str", "start": "str",
       "duration_minutes": "optional int, default 60",
       "location": "optional str"})
def calendar_add(title: str, start: str,
                 duration_minutes: int = 60, location: str = "") -> dict:
    when = _parse_when(start)
    if when is None:
        return {"ok": False,
                "message": f"Couldn't parse that time: '{start}'."}
    mem = _mem()
    mem.calendar_add(title.strip(), when, when + int(duration_minutes) * 60,
                     location=location or "")
    label = datetime.fromtimestamp(when).strftime("%a %H:%M")
    return {"ok": True, "title": title.strip(), "at": label}


@tool("calendar_cancel",
      "Cancel the soonest event whose title contains the given text.",
      {"title": "str"})
def calendar_cancel(title: str) -> dict:
    mem = _mem()
    victim = mem.calendar_remove(title.strip())
    if not victim:
        return {"ok": False,
                "message": f"No upcoming event matching '{title}'."}
    label = datetime.fromtimestamp(victim["start_ts"]).strftime("%a %H:%M")
    return {"ok": True, "cancelled": victim["title"], "was": label}
