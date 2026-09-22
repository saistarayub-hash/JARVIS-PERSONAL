"""Web watchers: JARVIS keeps reading pages so you don't have to.

Each watch re-fetches a URL on its own interval and compares:
  - content hash  -> "the page changed" alert with a fresh-text snippet
  - keyword       -> alert the first time the keyword appears
Failures are tracked honestly (unreachable-since) and announced once, not
spammy. Text-level only: no JS rendering, no logins, no form filling.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Callable, Optional

log = logging.getLogger("jarvis.webwatch")

_TAG = re.compile(r"(?s)<[^>]+>")


def _page_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", _TAG.sub(" ", html)).strip()


def _hash(text: str) -> str:
    return hashlib.md5(text[:20000].encode("utf-8", "replace")).hexdigest()[:16]


class WebWatchEngine:
    def __init__(self, memory, broadcast: Optional[Callable] = None,
                 min_interval_s: float = 30):
        self.memory = memory
        self._broadcast = broadcast or (lambda p: None)
        self.min_interval = min_interval_s

    def add(self, url: str, keyword: str = "", interval_s: float = 600) -> dict:
        if not re.match(r"^https?://", url):
            url = "https://" + url
        wid = self.memory.add_web_watch(url, keyword,
                                        max(self.min_interval, interval_s))
        note = f"watching every {int(max(self.min_interval, interval_s))}s"
        if keyword:
            note += f" for '{keyword}'"
        self._broadcast({"type": "webwatches",
                         "watches": self.memory.web_watches()})
        return {"ok": True, "id": wid, "url": url, "keyword": keyword,
                "note": note}

    def tick(self) -> list:
        import requests
        notes = []
        for w in self.memory.web_watches():
            now = time.time()
            if now - (w["last_check"] or 0) < w["interval_s"]:
                continue
            try:
                r = requests.get(w["url"], timeout=8, headers={
                    "User-Agent": "Mozilla/5.0 JARVIS-webwatch/1.0"})
                r.raise_for_status()
                text = _page_text(r.text)
            except Exception as exc:  # noqa: BLE001
                if "unreachable" not in (w["note"] or ""):
                    self.memory.update_web_watch(
                        w["id"], w["last_hash"], w["kw_seen"],
                        note=f"unreachable since {time.strftime('%H:%M')} "
                             f"({exc.__class__.__name__})")
                    msg = (f"I can't reach {w['url']} right now — I'll keep "
                           f"retrying every {int(w['interval_s'])}s.")
                    notes.append(msg)
                    self._broadcast({"type": "announce", "text": msg})
                    self._push()
                continue
            h = _hash(text)
            kw = (w["keyword"] or "").lower()
            kw_now = 1 if (kw and kw in text.lower()) else 0
            first = not w["last_hash"]
            if first:
                self.memory.update_web_watch(w["id"], h, kw_now,
                                             note="baseline taken")
                continue
            changed = h != w["last_hash"]
            kw_new = kw and kw_now and not w["kw_seen"]
            if changed or kw_new:
                snippet = text[:160]
                if kw_new:
                    msg = (f"Keyword '{w['keyword']}' just appeared on "
                           f"{w['url']}: \"{snippet}…\"")
                else:
                    msg = f"{w['url']} changed: \"{snippet}…\""
                notes.append(msg)
                self._broadcast({"type": "alert", "text": "🌐 " + msg})
                self._broadcast({"type": "announce", "text": msg})
            self.memory.update_web_watch(w["id"], h, kw_now, note="ok")
        if notes:
            self._push()
        return notes

    def list_text(self) -> str:
        rows = self.memory.web_watches()
        if not rows:
            return "No web watches armed."
        bits = []
        for w in rows:
            extra = f" for '{w['keyword']}'" if w["keyword"] else ""
            ago = int(time.time() - w["last_check"]) if w["last_check"] else -1
            state = w["note"] or ("checked " + str(ago) + "s ago"
                                  if ago >= 0 else "not checked yet")
            bits.append(f"{w['url']}{extra} every {int(w['interval_s'])}s "
                        f"[{state}]")
        return "Web watches: " + " · ".join(bits) + "."

    def _push(self) -> None:
        self._broadcast({"type": "webwatches",
                         "watches": self.memory.web_watches()})
