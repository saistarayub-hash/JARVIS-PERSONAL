"""Smart-home bridge: Home Assistant when configured, honest sim otherwise.

Real mode talks to a local HA instance over its REST API (long-lived token).
Sim mode (no config, or --demo) keeps an in-memory house so scenes and voice
commands remain exercisable — always labelled as simulated.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

log = logging.getLogger("jarvis.home")

SIM_LIGHTS = ["kitchen", "living", "bedroom", "desk"]


class HomeBridge:
    def __init__(self, cfg: dict, demo: bool = False,
                 broadcast: Optional[Callable] = None):
        hcfg = (cfg or {}).get("home_assistant") or {}
        self.url = (hcfg.get("url") or "").rstrip("/")
        self.token = hcfg.get("token") or ""
        self.demo = demo or not (self.url and self.token)
        self._broadcast = broadcast or (lambda p: None)
        self._lock = threading.RLock()
        self._sim: Dict = {
            "lights": {n: {"on": n in ("desk",), "brightness": 200}
                       for n in SIM_LIGHTS},
            "tv": {"on": False},
            "climate": {"temp": 22.0, "target": 22.0},
        }

    @property
    def label(self) -> str:
        return "home-assistant" if not self.demo else "sim home"

    # ---------------- public API ----------------
    def light(self, name: str, on: bool, brightness: Optional[int] = None) -> dict:
        name = (name or "all").lower()
        if not self.demo:
            svc = "light/turn_on" if on else "light/turn_off"
            data = {"entity_id": f"light.{name.replace(' ', '_')}"}
            if on and brightness is not None:
                data["brightness_pct"] = int(brightness)
            r = self._ha("light", svc.split("/")[1], data)
            if not r.get("ok"):
                return r
        else:
            with self._lock:
                targets = (list(self._sim["lights"]) if name == "all"
                           else [name if name in self._sim["lights"] else None])
                if targets == [None]:
                    return {"ok": False,
                            "message": f"No light called '{name}'. I know: "
                                       + ", ".join(self._sim["lights"]) + "."}
                for t in targets:
                    self._sim["lights"][t]["on"] = bool(on)
                    if brightness is not None:
                        self._sim["lights"][t]["brightness"] = int(brightness)
        self._push()
        return {"ok": True, "light": name, "on": bool(on),
                "brightness": brightness, "simulated": self.demo}

    def tv(self, on: bool) -> dict:
        if not self.demo:
            svc = "turn_on" if on else "turn_off"
            r = self._ha("media_player", svc,
                         {"entity_id": "media_player.tv"})
            if not r.get("ok"):
                return r
        else:
            self._sim["tv"]["on"] = bool(on)
        self._push()
        return {"ok": True, "tv": bool(on), "simulated": self.demo}

    def climate(self, target: float) -> dict:
        target = float(min(30, max(16, target)))
        if not self.demo:
            r = self._ha("climate", "set_temperature",
                         {"entity_id": "climate.home", "temperature": target})
            if not r.get("ok"):
                return r
        else:
            self._sim["climate"]["target"] = target
            self._sim["climate"]["temp"] = target
        self._push()
        return {"ok": True, "target": target, "simulated": self.demo}

    def state(self) -> dict:
        if not self.demo:
            r = self._get("/api/states")
            if r.get("ok"):
                lights, tv, climate = {}, {"on": False}, {"temp": 0, "target": 0}
                for st in r.get("states", []):
                    eid = st.get("entity_id", "")
                    attrs = st.get("attributes") or {}
                    if eid.startswith("light."):
                        lights[eid.split(".", 1)[1]] = {
                            "on": st.get("state") == "on",
                            "brightness": attrs.get("brightness", 0)}
                    elif eid == "media_player.tv":
                        tv = {"on": st.get("state") in ("on", "playing")}
                    elif eid.startswith("climate."):
                        climate = {"temp": st.get("current_temperature") or 0,
                                   "target": attrs.get("temperature") or 0}
                return {"ok": True, "simulated": False, "lights": lights,
                        "tv": tv, "climate": climate, "source": self.label}
        with self._lock:
            snap = json_copy(self._sim)
        return {"ok": True, "simulated": self.demo, **snap,
                "source": self.label}

    # ---------------- internals ----------------
    def _ha(self, domain: str, service: str, data: dict) -> dict:
        return self._post(f"/api/services/{domain}/{service}", data)

    def _post(self, path: str, data: dict) -> dict:
        import requests
        try:
            r = requests.post(self.url + path, json=data, timeout=8,
                              headers={"Authorization": f"Bearer {self.token}",
                                       "Content-Type": "application/json"})
            if r.status_code in (200, 201):
                return {"ok": True}
            return {"ok": False,
                    "message": f"Home Assistant said {r.status_code}: {r.text[:120]}"}
        except requests.RequestException as exc:
            return {"ok": False,
                    "message": f"Can't reach Home Assistant at {self.url} ({exc})."}

    def _get(self, path: str) -> dict:
        import requests
        try:
            r = requests.get(self.url + path, timeout=8,
                             headers={"Authorization": f"Bearer {self.token}"})
            if r.status_code == 200:
                return {"ok": True, "states": r.json()}
            return {"ok": False, "message": f"HA {r.status_code}"}
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}

    def _push(self) -> None:
        self._broadcast({"type": "home", **self.state()})


def json_copy(d: dict) -> dict:
    import json
    return json.loads(json.dumps(d))
