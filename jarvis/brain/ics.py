"""Minimal ICS (iCalendar) import — zero dependencies.

Handles the common personal-calendar shape: VEVENT with SUMMARY, DTSTART,
DTEND/DURATION (falls back to 1h), LOCATION, URL, DESCRIPTION.
Times are treated as local (floating or Z — good enough for a personal butler).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List


def _unesc(s: str) -> str:
    return (s or "").replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")


_DT = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?Z?$")


def _parse_dt(v: str):
    m = _DT.match((v or "").strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d, int(m.group(4) or 0),
                        int(m.group(5) or 0), int(m.group(6) or 0)).timestamp()
    except ValueError:
        return None


def parse_ics(text: str) -> List[Dict]:
    """Return [{title, start, end, location, url, notes}, ...] from ICS text."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: List[str] = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    events: List[Dict] = []
    cur: Dict | None = None
    for line in unfolded:
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT"):
            if cur:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, _, val = line.partition(":")
            key = key.split(";")[0].upper()
            if key in ("SUMMARY", "LOCATION", "URL", "DESCRIPTION",
                       "DTSTART", "DTEND", "DURATION", "STATUS"):
                cur[key] = val.strip()

    out = []
    for e in events:
        if (e.get("STATUS") or "").upper() == "CANCELLED":
            continue
        start = _parse_dt(e.get("DTSTART", ""))
        if start is None:
            continue
        end = _parse_dt(e.get("DTEND", ""))
        if end is None or end <= start:
            m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?", e.get("DURATION", ""))
            secs = 3600
            if m:
                secs = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
            end = start + max(secs, 900)
        title = _unesc(e.get("SUMMARY", "")).strip()
        if not title:
            continue
        out.append({
            "title": title[:200],
            "start": start,
            "end": end,
            "location": _unesc(e.get("LOCATION", "")).strip()[:200],
            "url": (e.get("URL", "") or "").strip()[:500],
            "notes": _unesc(e.get("DESCRIPTION", "")).strip()[:500],
        })
    out.sort(key=lambda ev: ev["start"])
    return out
