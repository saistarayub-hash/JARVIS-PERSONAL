"""Fleet tools — the LLM and rule brain can see and command every device."""
from __future__ import annotations

from . import tool

_shared: dict = {}


def set_hub(hub) -> None:
    _shared["hub"] = hub


def set_prep(engine) -> None:
    _shared["prep"] = engine


def _hub():
    hub = _shared.get("hub")
    if hub is None:
        raise RuntimeError("Fleet isn't enabled (set fleet.enabled: true).")
    return hub


@tool("fleet_status", "List all devices connected to JARVIS with their health.")
def fleet_status() -> dict:
    hub = _hub()
    devs = hub.summary()
    if not devs:
        return {"devices": [], "note": "No devices connected yet."}
    return {"devices": devs}


@tool("device_info", "Detailed status of one device.",
      {"name": "string (optional): device name — leave empty for the most recent"})
def device_info(name: str = "") -> dict:
    hub = _hub()
    devs = hub.summary()
    if not devs:
        raise RuntimeError("No devices connected yet.")
    target = next((d for d in devs if d["name"].lower() == (name or "").lower()), None)
    if target is None:
        if name:
            raise RuntimeError(f"Unknown device '{name}'. Connected: "
                               + ", ".join(d["name"] for d in devs))
        online = [d for d in devs if d["online"]]
        target = (online or devs)[-1]
    return {"device": target}


@tool("run_remote", "Run an allowed action on a device.",
      {"device": "string: device name",
       "action": "string: e.g. telemetry, disk, uptime, processes, activity, open_app, notify, shell",
       "args": "string (optional): JSON object of arguments, e.g. {\"cmd\": \"docker ps\"}"})
def run_remote(device: str, action: str, args: str = "") -> dict:
    import json as _json
    hub = _hub()
    parsed = {}
    if args:
        try:
            parsed = _json.loads(args)
        except json.JSONDecodeError:
            parsed = {"cmd": args}
    return hub.send(device, action, parsed)


@tool("fire_routine", "Run a named prep routine for the user (e.g. 'work', 'morning').",
      {"name": "string: routine name"})
def fire_routine(name: str) -> dict:
    prep = _shared.get("prep")
    if prep is None:
        raise RuntimeError("Prep engine isn't enabled.")
    return {"report": prep.fire_routine(name)}
