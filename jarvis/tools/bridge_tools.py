"""Bridge tools: smart home, music, scenes, phone SMS/calls, vision.

Each tool reaches a bridge object registered at startup. Real hardware when
configured/available (Home Assistant, playerctl, Termux on Android, a vision
model), clearly-labelled simulation otherwise.
"""
from __future__ import annotations

from . import tool

_shared: dict = {}


def set_bridges(home=None, music=None, jarvis=None) -> None:
    _shared["home"] = home
    _shared["music"] = music
    _shared["jarvis"] = jarvis


def _home():
    h = _shared.get("home")
    if h is None:
        raise RuntimeError("Home bridge isn't wired up.")
    return h


def _music():
    m = _shared.get("music")
    if m is None:
        raise RuntimeError("Music bridge isn't wired up.")
    return m


@tool("home_light", "Turn a smart light on/off, optionally with brightness %.",
      {"name": "string: light name or 'all'", "on": "boolean",
       "brightness": "optional integer 0-100"})
def home_light(name: str, on: bool, brightness: int | None = None) -> dict:
    return _home().light(name, bool(on),
                         None if brightness is None else int(brightness))


@tool("home_tv", "Turn the TV/media player on or off.", {"on": "boolean"})
def home_tv(on: bool) -> dict:
    return _home().tv(bool(on))


@tool("home_climate", "Set the home thermostat target temperature (C).",
      {"target": "number: degrees celsius, 16-30"})
def home_climate(target: float) -> dict:
    return _home().climate(float(target))


@tool("home_state", "Current state of lights, TV and climate.", {})
def home_state() -> dict:
    return _home().state()


@tool("music_control", "Control music: play [query], pause, next, volume 0-100.",
      {"action": "string: play|pause|next|volume|status",
       "query": "optional string: what to play (action=play)",
       "level": "optional integer: volume percent (action=volume)"})
def music_control(action: str, query: str = "", level: int | None = None) -> dict:
    m = _music()
    a = (action or "status").lower()
    if a == "play":
        return m.play(query or "")
    if a == "pause":
        return m.pause()
    if a in ("next", "skip"):
        return m.next()
    if a == "volume":
        return m.volume(int(level if level is not None else 40))
    return m.status()


@tool("run_scene", "Fire a named scene/routine (e.g. good-morning, movie-night, "
      "good-night): runs its whole action list in the background with a report.",
      {"name": "string: scene name"})
def run_scene(name: str) -> dict:
    j = _shared.get("jarvis")
    if j is None:
        raise RuntimeError("Core isn't wired up.")
    return {"ok": True, "reply": j.take_care(name)}


@tool("send_sms", "Send an SMS from the user's phone device (Termux agent).",
      {"device": "string: phone device name", "to": "string: number or contact",
       "text": "string: message body"})
def send_sms(device: str, to: str, text: str) -> dict:
    j = _shared.get("jarvis")
    if j is None or j.hub is None:
        raise RuntimeError("Fleet isn't enabled.")
    r = j.hub.send(device, "sms", {"to": to, "text": text})
    return r


@tool("place_call", "Place a phone call from the user's phone device (Termux).",
      {"device": "string: phone device name", "number": "string: number/contact"})
def place_call(device: str, number: str) -> dict:
    j = _shared.get("jarvis")
    if j is None or j.hub is None:
        raise RuntimeError("Fleet isn't enabled.")
    return j.hub.send(device, "call", {"number": number})


@tool("analyze_screen", "Capture a device's screen and describe what's on it "
      "(uses the vision model when one is connected).",
      {"device": "string: device name",
       "question": "optional string: what to look for"})
def analyze_screen(device: str, question: str = "") -> dict:
    j = _shared.get("jarvis")
    if j is None:
        raise RuntimeError("Core isn't wired up.")
    return j.see(device, question or "Describe what is on this screen.")

# ---------------------------------------------------------------- v9: push & browser
@tool("push_send", "Send a message to the user's phone (Telegram) or email. "
      "Without configured credentials it logs an honest simulated outbox entry.",
      {"text": "string: message to send",
       "channel": "optional string: telegram or mail"})
def push_send(text: str, channel: str | None = None) -> dict:
    jarvis = _shared.get("jarvis")
    if jarvis is None or getattr(jarvis, "push", None) is None:
        raise RuntimeError("Push bridge isn't wired up.")
    chans = [channel] if channel else None
    return {"pushed": jarvis.push.send(str(text), chans)}


@tool("browser_open", "Open a URL in a real headless browser (JS rendered, "
      "screenshot saved) when Playwright is installed; otherwise a plain-text "
      "fetch, clearly labelled 'JS not rendered'. Never fakes a browser.",
      {"url": "string: http(s) URL to open"})
def browser_open(url: str) -> dict:
    jarvis = _shared.get("jarvis")
    if jarvis is None or getattr(jarvis, "browser", None) is None:
        raise RuntimeError("Browser engine isn't wired up.")
    return jarvis.browser.open_page(str(url))
