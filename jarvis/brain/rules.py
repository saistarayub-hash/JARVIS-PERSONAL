"""Rule-based fallback brain.

Works with zero API keys and zero network config. This is the default brain
until you hook up an LLM (see README). It keeps JARVIS useful out of the box:
time, weather, apps, web search, memory, math, volume, files, fleet control,
prep routines, briefings, small talk.
"""
from __future__ import annotations

import datetime
import re
import time
from typing import Dict, Optional, Tuple

from ..tools import execute

HELP_TEXT = (
    "I can: tell the time and date, check the weather, open apps, search the web, "
    "find files, do math, adjust volume, check laptop health, tell jokes — and I "
    "learn what you tell me without being asked. Calendar: 'meetings today', "
    "'add a meeting with Sam at 3 pm', 'cancel design sync', 'import my calendar "
    "from work.ics'. Fleet: 'status of all devices', 'run disk on web-01', "
    "'watch web-01' (I'll alert you if it drops), 'screenshot my-mac' (what's on "
    "its screen). Prep: 'brief me', 'prep work', 'take care of work' (background, "
    "with a report back). 'quiet for 30 minutes' and I'll actually stay quiet."
)

CHITCHAT_FALLBACK = (
    "I'm running on my rule brain right now (no LLM connected), so that's a little "
    "outside my scripted repertoire. I can do: time, weather, open apps, web search, "
    "files, math, volume, laptop health, device status, briefings, prep routines — "
    "and I remember things. Type 'help' for the full list, or hook up an LLM in "
    "config.yaml for full JARVIS."
)

# pattern constants (matched on lowercased text)
RE_TIME    = r"^(?:what(?:'s| is)? )?the current time\b|^what time\b"
RE_DATE    = r"\bwhat(?:'s| is)? ? ?(?:the )?(?:date|day)(?: is it)?\b|today's date"
RE_WEATHER = (r"\bweather(?:\s+(?:like )?(?:in|for|at)\s+([a-z\s\-]+?))?"
              r"(?:\s+(?:today|tonight|right now|now))?\s*[?]?$")
RE_OPEN    = r"^(?:open|launch|start) (?:the )?([a-z0-9 _\-]+?)(?: please)?$"
RE_SEARCH  = r"^(?:search (?:for|up|the web for)|google|look up) (.+)$"
RE_REMEMBER = r"^(?:remember(?: that)?|keep in mind (?:that)?) (.+)$"
RE_KNOW_ME = r"what do you (?:know|remember) about me"
RE_BRIEF   = r"^(?:brief me|briefing|daily brief|morning brief|what'?:?s? next|status report)$"
RE_FLEET   = (r"^(?:what devices (?:are )?(?:online|connected|up)"
              r"|fleet (?:status|report)"
              r"|status (?:of|for) all devices"
              r"|which devices (?:are )?(?:online|connected)?)$")
RE_RUN_REMOTE = r"^(?:run|check) (?:shell )?(.+?) on ([a-z0-9_\-\.]+)$"
RE_DEVICE  = r"^(?:status of|how(?:'s| is)|check) ([a-z0-9_\-\.]+)(?: (?:status|health|report))?$"
RE_PREP    = r"^(?:prep|run) ([a-z0-9][a-z0-9 _\-]*)$"
RE_SUGGEST = r"\b(?:suggestions?|proactive|anything (?:to|you)|what should i)\b"
RE_PLAY    = r"^(?:play|put on) (.+)$"
RE_VOLUME_SET = r"volume (?:to |at )?(\d{1,3})\b"
RE_STATS   = r"how are you doing|system (?:stats|status|health)|laptop (?:status|health)"
RE_MATH    = r"^(?:calculate|compute|what(?:'s| is) )?(\d[\d\s\.\+\-\*/\(\)%]*\d[\d\.\)]?)\s*[=]?\??$"
RE_JOKE    = r"\bjoke\b"
RE_FILES   = (r"^(?:find|locate) (?:the |my )?(?:files?|documents?) "
              r"(?:called |named |matching )?(.+)$")
RE_CAL_LIST = (r"^(?:meetings?(?: today)?|what'?s on my calendar(?: today)?"
               r"|calendar(?: today)?|what am i doing(?: today| tomorrow)?"
               r"|next meeting|today'?s? plan)$")
RE_CAL_ADD = r"^add (?:a |an |my )?(meeting|call|appointment|deadline|task|event) (.+)$"
RE_CAL_CANCEL = r"^cancel (?:the )?(?:meeting |call |appointment |deadline |task |event )?(.+)$"
RE_CAL_IMPORT = r"^import (?:my )?(?:calendar|events|ics) from (\S+\.ics)$"
RE_SHOT = r"^(?:screenshot|capture|take a screenshot of|what'?s on the screen of) ([a-z0-9_\-\.]+)$"
RE_WATCH   = r"^(?:watch|keep an eye on|monitor) (?:on )?([a-z0-9_\-\.]+)$"
RE_UNWATCH = r"^(?:stop watching|stop monitoring|unwatch|no need to watch) ([a-z0-9_\-\.]+)$"
RE_TAKE_CARE = r"^take care of (.+)$"
RE_QUIET   = r"^(?:quiet|be quiet|shut up|stand by)(?: for (\d+) (minutes?|hours?))? ?(?:please)?$"
RE_QUIET_OFF = r"^(?:quiet off|cancel quiet|end quiet|wake up|stop being quiet|no more quiet)$"
RE_STOP    = r"^(?:stop|silence|zzz)$"
RE_HELP    = r"^(?:help|what can you do|commands|abilities)$"
RE_GREET   = r"^(?:hi|hello|hey|good (?:morning|afternoon|evening))\b"

SHELLY = ("docker", "git", "systemctl", "service", "pm2", "kubectl", "system",
          "free", "df", "top", "ps", "tail", "curl", "python")

# Fail fast: compile every pattern at import so a typo can't kill a live session.
for _name, _pat in list(globals().items()):
    if _name.startswith("RE_") and isinstance(_pat, str):
        re.compile(_pat)

HABIT_VERBS = {
    "open_app": "open {detail}",
    "active": "work in {detail}",
    "web_search": "search for {detail}",
    "weather": "check the weather",
    "set_volume": "adjust the volume",
}


def _extract(pattern: str, original: str, group: int = 1) -> str:
    """Pull a group out of the ORIGINAL text (preserves casing/punctuation)."""
    m = re.search(pattern, original, re.IGNORECASE)
    if m and m.lastindex is not None and m.lastindex >= group:
        return m.group(group).strip()
    return ""


def _match(original: str, jarvis=None) -> Optional[Tuple[str, Dict]]:
    t = re.sub(r"\s+", " ", original.strip().lower().rstrip(".!?"))
    if not t:
        return None
    orig = original.strip().rstrip(".!?")
    hub = getattr(jarvis, "hub", None) if jarvis else None
    devices = set(hub.names()) if hub else set()
    prep = getattr(jarvis, "prep", None) if jarvis else None
    routines = set(prep.routine_names()) if prep else set()

    if re.match(RE_TIME, t):
        return ("time", {})
    if re.search(RE_DATE, t):
        return ("date", {})
    if re.search(RE_WEATHER, t):
        city = _extract(RE_WEATHER, orig)
        return ("weather", {"city": city or None})
    if re.match(RE_OPEN, t):
        return ("open", {"app": _extract(RE_OPEN, orig) or t.split(" ", 1)[-1]})
    if re.match(RE_SEARCH, t):
        return ("search", {"q": _extract(RE_SEARCH, orig)})
    if re.match(RE_REMEMBER, t):
        return ("remember", {"fact": _extract(RE_REMEMBER, orig)})
    if re.search(RE_KNOW_ME, t):
        return ("know_me", {})
    if re.match(RE_BRIEF, t):
        return ("brief", {})
    if re.match(RE_FLEET, t):
        return ("fleet", {})
    m = re.match(RE_RUN_REMOTE, t)
    if m:
        return ("run_remote", {"action": m.group(1).strip(),
                               "device": m.group(2),
                               "shell": t.startswith(("run shell", "check shell"))})
    m = re.match(RE_DEVICE, t)
    if m and (not devices or m.group(1) in devices):
        return ("device", {"name": m.group(1)})
    m = re.match(RE_SHOT, t)
    if m and (not devices or m.group(1) in devices):
        return ("screenshot", {"name": m.group(1)})
    m = re.match(RE_CAL_LIST, t)
    if m:
        return ("calendar_list", {})
    m = re.match(RE_CAL_ADD, t)
    if m:
        return ("calendar_add", {"kind": m.group(1), "rest": m.group(2).strip()})
    m = re.match(RE_CAL_IMPORT, t)
    if m:
        return ("calendar_import", {"path": m.group(1)})
    m = re.match(RE_CAL_CANCEL, t)
    if m:
        return ("calendar_cancel", {"what": m.group(1).strip()})
    m = re.match(RE_WATCH, t)
    if m and (not devices or m.group(1) in devices):
        return ("watch", {"name": m.group(1)})
    m = re.match(RE_UNWATCH, t)
    if m:
        return ("unwatch", {"name": m.group(1)})
    m = re.match(RE_TAKE_CARE, t)
    if m:
        return ("take_care", {"name": m.group(1).strip()})
    m = re.match(RE_QUIET_OFF, t)
    if m:
        return ("quiet_off", {})
    m = re.match(RE_QUIET, t)
    if m:
        mins = int(m.group(1) or 15)
        unit = (m.group(2) or "minutes").lower()
        if unit.startswith("hour"):
            mins *= 60
        return ("quiet", {"minutes": min(mins, 60 * 12)})
    m = re.match(RE_PREP, t)
    if m and m.group(1) in routines:
        return ("prep", {"name": m.group(1)})
    if re.search(RE_SUGGEST, t):
        return ("suggestions", {})
    if re.match(RE_PLAY, t):
        return ("play", {"q": _extract(RE_PLAY, orig)})
    if "volume up" in t:
        return ("volume", {"action": "up"})
    if "volume down" in t:
        return ("volume", {"action": "down"})
    if re.search(RE_VOLUME_SET, t):
        return ("volume", {"action": "set", "level": re.search(RE_VOLUME_SET, t).group(1)})
    if re.search(r"\bmute\b", t):
        return ("volume", {"action": "mute"})
    if re.search(RE_STATS, t):
        return ("stats", {})
    m = re.match(RE_MATH, t)
    if m and re.search(r"[\+\-\*/]", m.group(1)):
        return ("math", {"expr": m.group(1).strip()})
    if re.search(RE_JOKE, t):
        return ("joke", {})
    if re.match(RE_FILES, t):
        return ("files", {"pattern": _extract(RE_FILES, orig)})
    if re.match(RE_STOP, t):
        return ("stop", {})
    if re.match(RE_HELP, t):
        return ("help", {})
    if re.match(RE_GREET, t) and len(t) <= 40:
        return ("greet", {})
    return None


def _fleet_bits(devs: list) -> list:
    bits = []
    for d in devs:
        t = d.get("telemetry") or {}
        extra = ", ".join(f"{k.replace('_pct', '')} {t[k]}%"
                          for k in ("cpu_pct", "ram_pct", "disk_pct", "battery_pct")
                          if k in t)
        if d["online"]:
            bits.append(f"{d['name']} ({d['os']}): {extra or 'up'}")
        else:
            bits.append(f"{d['name']}: offline {d['seen_ago']}s ago")
    return bits


def rule_respond(text: str, cfg: dict, memory, jarvis=None) -> Tuple[str, str, str, str]:
    """Returns (reply, intent, tool, detail)."""
    name = (cfg.get("user") or {}).get("name", "Boss")
    match = _match(text, jarvis)
    if match is None:
        return (CHITCHAT_FALLBACK, "chitchat", "", "")
    intent, args = match

    if intent == "greet":
        h = datetime.datetime.now().hour
        period = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
        return (f"Good {period}, {name}. Systems online — what do you need?", "greet", "", "")

    if intent == "time":
        return (f"It's {datetime.datetime.now().strftime('%H:%M')}.", "time", "", "")

    if intent == "date":
        return (f"Today is {datetime.datetime.now().strftime('%A, %d %B %Y')}.", "date", "", "")

    if intent == "brief":
        if jarvis is None:
            return ("The briefing engine isn't wired up.", "brief", "", "")
        return (jarvis.brief(), "brief", "brief", "")

    if intent == "fleet":
        hub = getattr(jarvis, "hub", None) if jarvis else None
        if hub is None:
            return ("Fleet isn't enabled — set fleet.enabled: true in config.yaml.",
                    "fleet", "", "")
        devs = hub.summary()
        if not devs:
            return ("No devices connected yet. On each machine run: "
                    "python -m jarvis.fleet.agent --name <device> --url "
                    "ws://<core>:8595 --token <token>. I'll take it from there.",
                    "fleet", "", "")
        up = sum(1 for d in devs if d["online"])
        return (f"Fleet check: {up}/{len(devs)} online. " + "; ".join(_fleet_bits(devs)) + ".",
                "fleet", "fleet_status", "")

    if intent == "device":
        hub = getattr(jarvis, "hub", None)
        devs = hub.summary() if hub else []
        target = next((d for d in devs if d["name"].lower() == args["name"]), None)
        if target is None:
            known = ", ".join(d["name"] for d in devs) or "none"
            return (f"I don't know a device called '{args['name']}'. Connected: {known}.",
                    "device", "device_info", args["name"])
        t = target.get("telemetry") or {}
        bits = [f"{target['name']} ({target['os']}):",
                "online" if target["online"] else f"offline {target['seen_ago']}s ago"]
        for k in ("cpu_pct", "ram_pct", "disk_pct", "battery_pct"):
            if k in t:
                bits.append(f"{k.replace('_pct', '')} {t[k]}%")
        act = target.get("activity") or {}
        if act.get("app"):
            bits.append(f"last activity: {act['app']}")
        return (" ".join(bits) + ".", "device", "device_info", args["name"])

    if intent == "run_remote":
        hub = getattr(jarvis, "hub", None)
        if hub is None:
            return ("Fleet isn't enabled.", "run_remote", "", args["device"])
        action = args["action"]
        is_shell = (args.get("shell") or " " in action
                    or action.split(" ", 1)[0].lower() in SHELLY)
        r = hub.send(args["device"],
                     "shell" if is_shell else action,
                     {"cmd": action} if is_shell else None)
        if r.get("ok"):
            data = r.get("data") or {}
            out = data.get("stdout")
            if out is None:
                if "used_pct" in data:
                    out = f"disk {data['used_pct']}% of {data.get('total_gb', '?')} GB used"
                elif "uptime_s" in data:
                    out = f"up for {data['uptime_s'] // 3600}h"
                elif "top" in data:
                    out = "top by memory: " + ", ".join(data["top"])
                else:
                    out = data.get("opened") or data.get("notified") or str(data)
            out = str(out)[:240].strip()
            return (f"On {args['device']}: {out or 'done'}",
                    "run_remote", "run_remote", args["device"])
        data = r.get("data") or {}
        msg = (r.get("message") or (data.get("stderr") or "").strip())[:160]
        if not msg:
            msg = "it didn't work"
        return (f"On {args['device']}: {msg}",
                "run_remote", "run_remote", args["device"])

    if intent == "prep":
        prep = getattr(jarvis, "prep", None)
        if prep is None:
            return ("Prep engine isn't enabled.", "prep", "", args["name"])
        return (prep.fire_routine(args["name"]), "prep", "fire_routine", args["name"])

    if intent == "watch":
        memory.watch(args["name"])
        return (f"On it. I'll keep an eye on {args['name']} and flag it the "
                "moment it drops.", "watch", "watch", args["name"])

    if intent == "unwatch":
        memory.unwatch(args["name"])
        return (f"Understood — I'll stop watching {args['name']}.",
                "unwatch", "unwatch", args["name"])

    if intent == "take_care":
        if jarvis is None:
            return ("I can't delegate right now.", "take_care", "", args["name"])
        return (jarvis.take_care(args["name"]), "take_care", "fire_routine",
                args["name"])

    if intent == "quiet":
        if jarvis is not None:
            jarvis.set_quiet(args["minutes"])
        return (f"Understood. I'll stay quiet for {args['minutes']} minutes — "
                "no suggestions, no alerts. Say 'quiet off' to bring me back.",
                "quiet", "quiet", "")

    if intent == "quiet_off":
        if jarvis is not None:
            jarvis.set_quiet(0)
        return ("Back to normal — proactivity re-enabled.", "quiet_off", "quiet", "")

    if intent == "calendar_list":
        now = datetime.datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0,
                                microsecond=0).timestamp()
        events = memory.calendar_events(time.time() - 3600, day_start + 86400)
        if not events:
            return ("Your calendar is clear for the rest of the day.",
                    "calendar", "calendar_today", "")
        bits = []
        for e in events:
            when = datetime.datetime.fromtimestamp(
                e["start_ts"]).strftime("%H:%M")
            loc = f" ({e['location']})" if e["location"] else ""
            bits.append(f"{when} {e['title']}{loc}")
        return ("Here's today: " + " · ".join(bits) + ".",
                "calendar", "calendar_today", "")

    if intent == "calendar_add":
        if jarvis is None:
            return ("The calendar engine isn't wired up.", "calendar", "", "")
        when = jarvis._learned_event(args["kind"], args["rest"])
        if when is None:
            return ("At what time? Try 'add a meeting with Sam at 3 pm'.",
                    "calendar", "", "")
        return (f"Added to your calendar — {when}. I'll have you ready "
                "before it starts.", "calendar", "calendar_add", when)

    if intent == "calendar_cancel":
        victim = memory.calendar_remove(args["what"])
        if victim:
            label = datetime.datetime.fromtimestamp(
                victim["start_ts"]).strftime("%a %H:%M")
            return (f"Cancelled '{victim['title']}' ({label}).",
                    "calendar", "calendar_cancel", victim["title"])
        return (f"I couldn't find anything upcoming matching '{args['what']}'.",
                "calendar", "calendar_cancel", args["what"])

    if intent == "calendar_import":
        import os
        from .ics import parse_ics
        path = os.path.expanduser(args["path"])
        if not os.path.isfile(path):
            return (f"I can't read {path} — no such file.", "calendar", "", path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                events = parse_ics(fh.read())
        except Exception as exc:  # noqa: BLE001
            return (f"That file isn't readable ICS ({exc}).", "calendar", "", path)
        now_ts = time.time()
        future = [e for e in events if e["start"] > now_ts]
        for e in future:
            memory.calendar_add(e["title"], e["start"], e["end"],
                                e["location"], e["url"], e["notes"])
        if not future:
            return ("That file had no upcoming events.", "calendar", "", path)
        return (f"Imported {len(future)} upcoming events from "
                f"{os.path.basename(path)}.", "calendar", "", path)

    if intent == "screenshot":
        hub = getattr(jarvis, "hub", None)
        if hub is None:
            return ("Fleet isn't enabled.", "screenshot", "", args["name"])
        r = hub.send(args["name"], "screenshot")
        if r.get("ok") and r.get("url"):
            return (f"Got it — {args['name']}'s screen is up on the overlay.",
                    "screenshot", "screenshot", args["name"])
        msg = (r.get("message") or "it didn't work")[:160]
        return (f"Couldn't screenshot {args['name']}: {msg}",
                "screenshot", "screenshot", args["name"])

    if intent == "weather":
        city = args.get("city")
        r = execute("weather", cfg=cfg, city=city)
        if not r["ok"]:
            return (r["message"], "weather", "weather", (city or ""))
        w = r["result"]
        return (f"In {w['city']}: {w['temp_c']}°C, feels like {w['feels_c']}°, "
                f"{w['conditions']}.", "weather", "weather", (w.get("city") or ""))

    if intent == "open":
        r = execute("open_app", cfg=cfg, name=args["app"])
        if r["ok"]:
            return (f"Opening {args['app']}.", "open", "open_app", args["app"])
        return (r.get("message", "Sorry, I couldn't open that."), "open", "open_app", args["app"])

    if intent == "search":
        r = execute("web_search", cfg=cfg, query=args["q"], max_results=3)
        if not r["ok"]:
            return (r["message"], "search", "web_search", args["q"])
        res = r["result"]["results"]
        top = res[0]
        extra = (" — also: " + "; ".join(x["title"] for x in res[1:])) if len(res) > 1 else ""
        return (f"Top hit: {top['title']} — {top['url']}{extra}.", "search", "web_search", args["q"])

    if intent == "remember":
        if memory.remember(args["fact"]):
            return (f"Noted. I'll remember that {args['fact']}.", "remember", "remember_fact", "")
        return ("I already had that one filed.", "remember", "remember_fact", "")

    if intent == "know_me":
        facts = [f["text"] for f in memory.facts()[:6]]
        if not facts:
            return ("Honest answer? Not much yet. Tell me something and I'll file it — "
                    "try 'remember I like lo-fi in the evening'.", "know_me", "", "")
        return ("Here's what's on file: " + " | ".join(facts) + ".", "know_me", "", "")

    if intent == "suggestions":
        habits = memory.matches_now(window_hours=1)
        if habits:
            parts = []
            for h in habits[:3]:
                verb = HABIT_VERBS.get(h["tool"], f"use '{h['tool']}'")
                if h["detail"] and "{detail}" in verb:
                    verb = verb.format(detail=h["detail"])
                parts.append(f"you usually {verb} around {h['hour']:02d}:00")
            return ("Based on what I've learned — " + ", and ".join(parts)
                    + ". Want me to get ahead of it?", "suggestions", "", "")
        return ("Nothing feels time-critical right now. I learn your habits as you use "
                "me — the more you lean on me, the sharper it gets.", "suggestions", "", "")

    if intent == "play":
        r = execute("open_app", cfg=cfg, name="spotify")
        if r["ok"]:
            return (f"Opening Spotify. I'd queue '{args['q']}' for you, but I don't drive "
                    "the player yet — one tap on your end.", "play", "open_app", args["q"])
        return ("I'd open Spotify for that, but it's not installed (or I can't find it) "
                "on this machine.", "play", "open_app", args["q"])

    if intent == "volume":
        r = execute("set_volume", cfg=cfg, action=args["action"], level=args.get("level"))
        if r["ok"]:
            return (r["result"].get("detail", "Volume adjusted."), "volume", "set_volume", args["action"])
        return (r["message"], "volume", "set_volume", args["action"])

    if intent == "stats":
        r = execute("system_stats", cfg=cfg)
        s = r["result"]
        bits = [s["platform"], f"{s['cpu_count']} cores"]
        if "cpu_load_1m" in s:
            bits.append(f"CPU load {s['cpu_load_1m']}")
        if "ram_used_pct" in s:
            bits.append(f"RAM {s['ram_used_pct']}% used")
        if "battery_pct" in s:
            bits.append(f"battery {s['battery_pct']}%")
        note = f" {s['note']}" if s.get("note") else ""
        return ("Status report: " + ", ".join(bits) + note + ".", "stats", "system_stats", "")

    if intent == "math":
        r = execute("math", cfg=cfg, expression=args["expr"])
        if r["ok"]:
            return (f"That's {r['result']['value']}.", "math", "math", "")
        return ("I couldn't parse that expression.", "math", "math", "")

    if intent == "joke":
        return (execute("joke", cfg=cfg)["result"]["joke"], "joke", "joke", "")

    if intent == "files":
        r = execute("find_files", cfg=cfg, pattern=args["pattern"])
        found = r["result"]["found"]
        if not found:
            return (f"No files matching '{args['pattern']}' in your usual folders.",
                    "files", "find_files", "")
        return (f"Found {len(found)} — e.g. " + ", ".join(found[:3]) + ".",
                "files", "find_files", "")

    if intent == "stop":
        return ("Standing by.", "stop", "", "")

    if intent == "help":
        return (HELP_TEXT, "help", "", "")

    return (CHITCHAT_FALLBACK, "chitchat", "", "")
