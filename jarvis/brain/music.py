"""Music bridge: real MPRIS control via playerctl, honest sim otherwise.

On Linux (and any box with playerctl) this drives whatever media player is
running — Spotify, VLC, browser tabs. 'play <query>' opens a Spotify search
deeplink when no player is active. Sim mode keeps a little playlist so scenes
and voice commands work offline, always labelled.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Callable, Optional

log = logging.getLogger("jarvis.music")

SIM_PLAYLIST = [
    ("Interstellar — Working Out", "Hans Zimmer"),
    ("Weightless", "Marconi Union"),
    ("Lofi beats for debugging", "JARVIS sim radio"),
    ("Time", "Hans Zimmer"),
]


class MusicBridge:
    def __init__(self, demo: bool = False,
                 broadcast: Optional[Callable] = None):
        self.demo = demo
        self._broadcast = broadcast or (lambda p: None)
        self._lock = threading.RLock()
        self._i = 0
        self._playing = False
        self._volume = 40

    @property
    def label(self) -> str:
        return "playerctl" if self._have_playerctl() else "sim player"

    @staticmethod
    def _have_playerctl() -> bool:
        return shutil.which("playerctl") is not None

    def _ctl(self, *args) -> Optional[str]:
        if not self._have_playerctl():
            return None
        try:
            r = subprocess.run(["playerctl", *args], capture_output=True,
                               text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    # ---------------- public API ----------------
    def play(self, query: str = "") -> dict:
        if self._have_playerctl() and not self.demo:
            if query:
                self._open_search(query)
                self._ctl("play")
                self._push()
                return {"ok": True, "playing": query, "simulated": False,
                        "note": "opened a Spotify search for it"}
            if self._ctl("play") is not None:
                self._push()
                return {"ok": True, "playing": self.status().get("track"),
                        "simulated": False}
            self._open_search(query or "focus music")
            self._push()
            return {"ok": True, "playing": query or "focus music",
                    "simulated": False, "note": "opened Spotify for it"}
        with self._lock:
            self._playing = True
            track, artist = SIM_PLAYLIST[self._i % len(SIM_PLAYLIST)]
        self._push()
        return {"ok": True, "playing": f"{track} — {artist}",
                "simulated": True}

    def pause(self) -> dict:
        self._ctl("pause")
        with self._lock:
            self._playing = False
        self._push()
        return {"ok": True, "playing": False, "simulated": self.demo}

    def next(self) -> dict:
        if self._have_playerctl() and not self.demo and self._ctl("next") is not None:
            self._push()
            return {"ok": True, "simulated": False, **self.status()}
        with self._lock:
            self._i += 1
            self._playing = True
            track, artist = SIM_PLAYLIST[self._i % len(SIM_PLAYLIST)]
        self._push()
        return {"ok": True, "playing": f"{track} — {artist}", "simulated": True}

    def volume(self, pct: int) -> dict:
        pct = int(min(100, max(0, pct)))
        self._ctl("volume", str(pct / 100))
        with self._lock:
            self._volume = pct
        self._push()
        return {"ok": True, "volume": pct, "simulated": self.demo}

    def status(self) -> dict:
        if self._have_playerctl() and not self.demo:
            meta = self._ctl("metadata", "--format",
                             "{{title}} — {{artist}}")
            st = self._ctl("status")
            if meta is not None or st is not None:
                return {"ok": True, "simulated": False,
                        "track": meta or "", "playing": st == "Playing",
                        "volume": self._volume, "source": self.label}
        with self._lock:
            track, artist = SIM_PLAYLIST[self._i % len(SIM_PLAYLIST)]
            return {"ok": True, "simulated": True,
                    "track": f"{track} — {artist}" if self._playing else "",
                    "playing": self._playing, "volume": self._volume,
                    "source": self.label}

    # ---------------- internals ----------------
    @staticmethod
    def _open_search(query: str) -> None:
        import webbrowser
        from urllib.parse import quote
        try:
            webbrowser.open(f"https://open.spotify.com/search/{quote(query)}")
        except Exception:  # noqa: BLE001 — headless box, no browser
            log.debug("no browser to open spotify search")

    def _push(self) -> None:
        self._broadcast({"type": "music", **self.status()})
