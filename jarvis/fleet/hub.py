"""DeviceHub — the core-side registry for all connected devices.

Agents (laptops, servers, phones) connect over WebSocket with a shared token,
heartbeat with telemetry, stream activity/events, and answer allowed commands.
Everything is in-memory + persisted to SQLite for last-seen.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("jarvis.fleet")


class Device:
    def __init__(self, name: str, os: str, meta: dict):
        self.name = name
        self.os = os
        self.meta = dict(meta or {})
        self.last_seen = time.time()
        self.telemetry: dict = {}
        self.connected = False
        self.last_activity: dict = {}
        self.offline_since: Optional[float] = None
        self._ws = None            # live WebSocket (real agents)
        self._cmd_handler: Optional[Callable] = None  # in-process (sim agents)

    def summary(self) -> dict:
        return {
            "name": self.name, "os": self.os, "meta": self.meta,
            "online": self.connected,
            "seen_ago": int(time.time() - self.last_seen),
            "telemetry": self.telemetry,
            "activity": self.last_activity,
        }


class DeviceHub:
    def __init__(self, memory, cfg: dict,
                 broadcast: Optional[Callable] = None):
        self.memory = memory
        self.cfg = cfg.get("fleet", {}) or {}
        self._broadcast = broadcast or (lambda p: None)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: Dict[str, tuple] = {}
        self.devices: Dict[str, Device] = {}
        self._last_fleet_push = 0.0
        for row in self.memory.device_rows():
            try:
                meta = json.loads(row["meta"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            d = Device(row["name"], row["os"], meta)
            d.last_seen = row["last_seen"] or time.time()
            self.devices[d.name] = d

    def set_loop(self, loop) -> None:
        self._loop = loop

    # ---- registry ----
    def register(self, name: str, os: str, meta: dict,
                 cmd_handler: Optional[Callable] = None):
        """Returns (device, offline_seconds) — 0 if it was never seen down."""
        d = self.devices.get(name) or Device(name, os, meta)
        was_out = (time.time() - d.offline_since) if d.offline_since else 0.0
        d.connected = True
        d.offline_since = None
        d.last_seen = time.time()
        if os:
            d.os = os
        if meta:
            d.meta = {**d.meta, **meta}
        if cmd_handler is not None:
            d._cmd_handler = cmd_handler
        self.devices[name] = d
        self.memory.upsert_device(name, d.os, json.dumps(d.meta))
        log.info("device '%s' connected (%s)", name, d.os)
        self._fleet_update(force=True)
        return d, was_out

    def mark_gone(self, name: str) -> bool:
        """Returns True if the device transitioned online -> offline."""
        d = self.devices.get(name)
        if d and d.connected:
            d.connected = False
            d.offline_since = time.time()
            d.last_seen = time.time()
            self.memory.upsert_device(name, d.os, json.dumps(d.meta))
            log.info("device '%s' disconnected", name)
            self._fleet_update(force=True)
            return True
        return False

    def on_heartbeat(self, name: str, telemetry: dict) -> None:
        d = self.devices.get(name)
        if not d:
            return
        d.last_seen = time.time()
        d.telemetry = telemetry or {}
        self.memory.upsert_device(name, d.os, json.dumps(d.meta))
        self._fleet_update()

    def on_event(self, name: str, kind: str, data: dict) -> None:
        d = self.devices.get(name)
        if d:
            d.last_seen = time.time()
            if kind == "activity":
                d.last_activity = data
        self._broadcast({"type": "fleet_event", "device": name,
                         "kind": kind, "data": data})

    def _fleet_update(self, force: bool = False) -> None:
        """Throttled UI push (telemetry heartbeats are chatty)."""
        now = time.time()
        if not force and now - self._last_fleet_push < 5:
            return
        self._last_fleet_push = now
        self._broadcast({"type": "fleet", "devices": self.summary()})

    def summary(self) -> List[dict]:
        return [d.summary() for d in self.devices.values()]

    def names(self) -> List[str]:
        return list(self.devices.keys())

    # ---- command dispatch ----
    def send(self, name: str, action: str, args: Optional[dict] = None,
             timeout: float = 20.0) -> Dict[str, Any]:
        """Send a command to a device and wait for its result."""
        d = self.devices.get(name)
        if d is None:
            known = ", ".join(self.devices) or "none yet"
            return {"ok": False,
                    "message": f"Unknown device '{name}'. Connected: {known}."}
        if d._cmd_handler is not None:
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(d._cmd_handler, action, args or {})
            try:
                res = fut.result(timeout=timeout)
            except Exception as exc:
                return {"ok": False, "message": str(exc)}
            return self._post_screenshot(name, res, action)
        if not d.connected or d._ws is None or self._loop is None \
                or not self._loop.is_running():
            ago = int(time.time() - d.last_seen)
            return {"ok": False,
                    "message": f"'{name}' is offline (last seen {ago}s ago)."}
        cid = uuid.uuid4().hex[:8]
        result: Future = Future()
        self._pending[cid] = result
        payload = {"type": "cmd", "id": cid, "action": action, "args": args or {}}

        async def _do_send():
            try:
                await d._ws.send_json(payload)
            except Exception as exc:
                if not result.done():
                    result.set_exception(exc)

        try:
            asyncio.run_coroutine_threadsafe(_do_send(), self._loop).result(3)
        except Exception as exc:
            self._pending.pop(cid, None)
            return {"ok": False, "message": f"couldn't reach {name}: {exc}"}
        try:
            res = result.result(timeout=timeout)
        except Exception as exc:
            return {"ok": False, "message": f"no result from {name} ({exc})"}
        return self._post_screenshot(name, res, action)

    def _post_screenshot(self, name: str, res: dict, action: str) -> dict:
        if action == "screenshot" and isinstance(res, dict) and res.get("ok"):
            url = self.store_screenshot(name, res)
            if url:
                res = {**res, "url": url}
                res.pop("data_b64", None)
        return res

    def _resolve(self, cid: str, result: dict) -> None:
        fut = self._pending.pop(cid, None)
        if fut is not None and not fut.done():
            fut.set_result(result)

    # ---- screenshots ----
    def _shot_dir(self) -> str:
        import os
        root = os.path.dirname(os.path.abspath(
            getattr(self.memory, "db_path", "") or "data/memory.db"))
        return os.path.join(root, "screenshots")

    def store_screenshot(self, device: str, result: dict) -> str | None:
        """Persist a base64 PNG from a device; returns its URL or None."""
        import base64
        import os
        b64 = (result or {}).get("data_b64")
        if not b64:
            return None
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return None
        d = self._shot_dir()
        os.makedirs(d, exist_ok=True)
        safe_dev = re.sub(r"[^a-z0-9_\-]", "_", device.lower())
        fname = f"{safe_dev}_{int(time.time())}.png"
        with open(os.path.join(d, fname), "wb") as fh:
            fh.write(raw)
        url = f"/api/screenshots/{fname}"
        self._broadcast({"type": "screenshot", "device": device, "url": url})
        return url

    def screenshot_dir(self) -> str:
        return self._shot_dir()
