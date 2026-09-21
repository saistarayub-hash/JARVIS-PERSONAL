"""Browser engine (v9): real headless Chromium via Playwright when installed.

Honesty rule: if Playwright (or its Chromium binary) isn't present, this says
so plainly and offers the plain-text fetch instead — always labelled
"JS not rendered". It never fakes a browser.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("jarvis.browser")


class BrowserEngine:
    def __init__(self, cfg: Optional[dict], root: str = ".",
                 demo: bool = False):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.timeout_s = float(cfg.get("timeout_s", 20))
        self.shots_dir = Path(root) / "data" / "shots"
        self.demo = demo

    # ------------------------------------------------------------ capability
    def available(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "disabled in config"}
        if importlib.util.find_spec("playwright") is None:
            return {"ok": False,
                    "reason": "the playwright package isn't installed here"}
        cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or
                     (Path.home() / ".cache" / "ms-playwright"))
        if not cache.exists() or not any(
                p.name.startswith("chromium") for p in cache.iterdir()):
            return {"ok": False,
                    "reason": ("playwright is installed but its Chromium "
                               "browser hasn't been downloaded "
                               "(playwright install chromium)")}
        return {"ok": True, "engine": "playwright/chromium"}

    # ------------------------------------------------------------ rendering
    def fetch(self, url: str, screenshot: bool = True) -> Dict[str, Any]:
        """Render url in a real browser: title, visible text, screenshot."""
        av = self.available()
        if not av.get("ok"):
            return {"ok": False, "available": False, "url": url,
                    "reason": av.get("reason", "browser unavailable")}

        def _work() -> Dict[str, Any]:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(
                        viewport={"width": 1280, "height": 900})
                    page.goto(url, timeout=self.timeout_s * 1000,
                              wait_until="domcontentloaded")
                    title = page.title()
                    try:
                        text = page.inner_text("body")[:6000]
                    except Exception:  # noqa: BLE001
                        text = ""
                    shot = None
                    if screenshot:
                        self.shots_dir.mkdir(parents=True, exist_ok=True)
                        slug = re.sub(r"[^a-z0-9]+", "-", url.lower())[:48]
                        slug = slug.strip("-") or "page"
                        shot = str(self.shots_dir /
                                   f"{slug}-{int(time.time())}.png")
                        page.screenshot(path=shot)
                    return {"ok": True, "available": True, "url": url,
                            "title": title, "text": text.strip(),
                            "screenshot": shot, "rendered": True}
                finally:
                    browser.close()

        try:
            return _work()
        except Exception as exc:  # noqa: BLE001 — honest failure
            return {"ok": False, "available": True, "url": url,
                    "error": f"{exc.__class__.__name__}: {exc}"}

    # ------------------------------------------------------------ fallback
    def fallback_text(self, url: str) -> Dict[str, Any]:
        """Plain-text fetch (the v5 read_url path), used when no browser
        engine is present. Always labelled: JS was NOT rendered."""
        from ..tools.web import read_url
        if not re.match(r"^https?://", url or ""):
            url = "https://" + (url or "")
        try:
            got = read_url(url)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "url": url,
                    "error": str(exc), "rendered": False}
        return {"ok": True, "available": False, "url": url,
                "title": got.get("title", ""), "text": got.get("text", ""),
                "rendered": False}

    def open_page(self, url: str) -> Dict[str, Any]:
        """One call used by the brain: render if possible, otherwise fetch
        plain text with an honest note. Never raises for missing engines."""
        res = self.fetch(url)
        if res.get("ok"):
            return res
        fb = self.fallback_text(url)
        fb["reason"] = res.get("reason") or res.get("error") or \
            "browser unavailable"
        return fb
