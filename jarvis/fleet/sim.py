"""Simulated fleet devices for demos — no real hardware attached.

Run the core with `python run.py --demo` and two convincing devices
(a Linux server and a phone) join the fleet, heartbeat, stream activity
and answer commands — so you can feel the whole fleet experience.
"""
from __future__ import annotations

import logging
import random
import threading
import time

log = logging.getLogger("jarvis.fleet.sim")

_APP_SCHEDULES = {
    "web-01": [("VS Code", 150), ("Terminal", 90), ("Chrome", 60)],
    "phone": [("WhatsApp", 180), ("Chrome", 90), ("Spotify", 120)],
}


class SimAgent(threading.Thread):
    def __init__(self, hub, name: str, os: str, meta: dict,
                 on_event=None, jarvis=None):
        super().__init__(daemon=True, name=f"sim-{name}")
        self.hub = hub
        self.name = name
        self.os = os
        self.meta = meta
        self.jarvis = jarvis
        self.emit = on_event or hub.on_event  # Jarvis.note_device_event preferred
        self._stop = threading.Event()
        self._cpu = random.uniform(8, 30)
        self._ram = random.uniform(35, 60)
        self._disk = random.uniform(40, 75)
        self._battery = 100 if name != "phone" else 64
        self._app = ""
        self._app_left = 0
        self._cycle = 0

    def stop(self) -> None:
        self._stop.set()

    # ---- command answers (the core can "run things" on the sim) ----
    def _cmd(self, action: str, args: dict) -> dict:
        a = (action or "").lower()
        if a == "telemetry":
            return {"ok": True, "data": self._telemetry()}
        if a == "disk":
            return {"ok": True, "data": {"total_gb": 480,
                                         "used_pct": int(self._disk)}}
        if a == "uptime":
            return {"ok": True, "data": {"uptime_s": 34 * 3600}}
        if a == "processes":
            return {"ok": True, "data": {"top": [
                "node (mem 12%)", "postgres (mem 8%)", "nginx (mem 3%)",
                "redis-server (mem 2%)"]}}
        if a == "activity":
            return {"ok": True, "data": {"app": self._app}}
        if a == "open_app":
            return {"ok": True, "data": {"opened": args.get("name", "")}}
        if a == "screenshot":
            return self._fake_screen()
        if a == "notify":
            return {"ok": True, "data": {"notified": args.get("text", "")}}
        if a == "shell":
            cmd = (args.get("cmd") or "").lower()
            if cmd.startswith("docker"):
                return {"ok": True, "data": {"code": 0, "stdout":
                    "CONTAINER    STATUS\napi-1        Up 3h (healthy)\n"
                    "web-1        Up 3h (healthy)\nredis-1    Up 2d (healthy)"}}
            if cmd.startswith("git"):
                return {"ok": True, "data": {"code": 0, "stdout":
                    "On branch main\nnothing to commit, working tree clean"}}
            if cmd.startswith("systemctl") or cmd.startswith("service"):
                return {"ok": True, "data": {"code": 0, "stdout":
                    "nginx.service active (running)\npostgres.service active (running)"}}
            return {"ok": False, "message": "shell command not in allowlist"}
        return {"ok": False, "message": f"unknown action '{action}'"}

    def _telemetry(self) -> dict:
        t = {"os": f"{self.os} (simulated)", "host": self.name,
             "cpu_pct": int(max(2, min(98, self._cpu + random.uniform(-3, 3)))),
             "ram_pct": int(max(5, min(97, self._ram + random.uniform(-2, 2)))),
             "disk_pct": int(self._disk)}
        if self.name == "phone":
            t["battery_pct"] = int(self._battery)
        else:
            t["uptime_s"] = 34 * 3600
        return t

    def _next_app(self):
        schedule = _APP_SCHEDULES.get(self.name, [("Terminal", 120)])
        app, secs = schedule[self._cycle % len(schedule)]
        self._cycle += 1
        return app, secs

    def _fake_screen(self) -> dict:
        """A plausible fake desktop, hand-rolled into a PNG (no PIL here)."""
        import base64
        import struct
        import zlib
        from datetime import datetime
        w, h = 320, 200
        name_bytes = self.name.encode()[:12]
        clock = datetime.now().strftime("%H:%M").encode()
        rows = bytearray()
        for y in range(h):
            rows.append(0)  # PNG filter: none
            for x in range(w):
                r, g, b = 12 + (x * 14) // w, 16 + (y * 22) // h, 30 + ((x + y) * 24) // (w + h)
                if 30 <= y < 170 and 20 <= x < 230:           # main window
                    r, g, b = 38, 50, 72
                    if 30 <= y < 44:                           # title bar
                        r, g, b = 84, 100, 132
                if 240 <= x < 300 and 30 <= y < 90:            # side panel
                    r, g, b = 30, 40, 58
                if 10 <= x < 10 + len(name_bytes) and 178 <= y < 192:
                    if name_bytes[x - 10] % 3 == 0:
                        r, g, b = 150, 190, 255
                if 240 <= x < 240 + len(clock) * 5 and 178 <= y < 192:
                    r, g, b = 140, 230, 170
                rows += bytes((r, g, b))

        def chunk(tag: bytes, data: bytes) -> bytes:
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
               + chunk(b"IEND", b""))
        return {"ok": True, "data_b64": base64.b64encode(png).decode()}

    # ---- main loop ----
    def run(self) -> None:
        self.hub.register(self.name, self.os, self.meta,
                          cmd_handler=self._cmd)
        self._app, self._app_left = self._next_app()
        # warm-up: the user has already been using this device all day
        from datetime import datetime
        now = datetime.now()
        if self.name == "web-01":
            for app, hh, mm, secs in [
                ("VS Code", 9, 0, 2400), ("VS Code", 9, 45, 1500),
                ("Chrome", 10, 30, 1200), ("Chrome", 10, 50, 900),
                ("Terminal", 11, 30, 1500),
            ]:
                if hh > now.hour or (hh == now.hour and mm > now.minute):
                    continue
                self.emit(self.name, "activity",
                          {"app": app, "seconds": secs,
                           "title": f"on {self.name}"})
        self.emit(self.name, "activity",
                          {"app": self._app, "seconds": 1100,
                           "title": f"on {self.name}"})
        self._stop.wait(6)
        self.emit(self.name, "activity",
                          {"app": self._app, "seconds": 600,
                           "title": f"on {self.name}"})
        # the phone drops once for a couple of minutes (watcher demo)
        if self.name == "phone" and self.jarvis is not None:
            started = time.time()
            flap_at, out_for = 45.0, 100.0
            gone_at = None
            flap_done = False
        while not self._stop.is_set():
            self._stop.wait(4)
            if self._stop.is_set():
                break
            if (self.name == "phone" and self.jarvis is not None
                    and not flap_done):
                now_t = time.time()
                if gone_at is None and now_t - started > flap_at:
                    if self.hub.mark_gone(self.name):
                        self.jarvis.on_device_gone(self.name)
                    gone_at = now_t
                elif gone_at is not None and now_t - gone_at > out_for:
                    self.hub.register(self.name, self.os, self.meta,
                                      cmd_handler=self._cmd)
                    self.jarvis.on_device_back(self.name, now_t - gone_at)
                    gone_at = None
                    flap_done = True
            self._cpu = max(2, min(98, self._cpu + random.uniform(-4, 4)))
            self._ram = max(5, min(97, self._ram + random.uniform(-2, 2)))
            if self.name == "phone":
                self._battery = max(5, self._battery - 0.05)
            self.hub.on_heartbeat(self.name, self._telemetry())
            self._app_left -= 4
            if self._app_left <= 0:
                self.emit(self.name, "activity", {
                    "app": self._app, "seconds": self._app_left + 4,
                    "title": f"on {self.name}"})
                self._app, self._app_left = self._next_app()
            if random.random() < 0.02:
                self.emit(self.name, "service", {
                    "name": random.choice(["nginx", "postgres", "docker"]),
                    "state": "ok"})
        self.hub.mark_gone(self.name)
