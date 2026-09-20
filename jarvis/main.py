"""Jarvis: the orchestrator — memory, learning, prep, fleet, brains, UI.

The "figurative made real" layer lives here:
- auto-learning facts from ordinary conversation (no 'remember' needed)
- time-aware facts becoming scheduled preps ("I open VS Code at 9")
- sequence detection offering to save routines it noticed
- watchers that actually keep an eye on every device
- 'take care of it' background execution with progress reports
- quiet mode that actually stays quiet
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from .brain import LLMBrain, Memory, rule_respond
from .brain.prep import PrepEngine
from .fleet.hub import DeviceHub
from .learner import Learner
from .tools.fleet import set_hub as set_fleet_hub
from .tools.fleet import set_prep as set_prep_tool
from .tools.memory_tools import set_memory
from .tools.market_tools import set_markets
from .tools.bridge_tools import set_bridges
from .tools import web as web_tools
from .brain.fx import Markets
from .brain.home import HomeBridge
from .brain.music import MusicBridge

log = logging.getLogger("jarvis")

_VERB_NOUNS = {"like": "likes", "love": "loves", "prefer": "prefers",
               "enjoy": "enjoys", "want": "wants", "want to": "wants to"}
_NOUNS = ("phone", "laptop", "server", "car", "bank", "doctor", "gym",
          "job", "apartment", "house")


class Jarvis:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        root = cfg.get("root") or "."
        self.memory = Memory(os.path.join(root, cfg["memory"]["db"]))
        set_memory(self.memory)
        self.demo = bool(cfg.get("demo", False))
        web_tools.set_demo(self.demo)
        self.markets = Markets(cfg, demo=self.demo)
        set_markets(self.markets)
        self.home = HomeBridge(cfg, demo=self.demo, broadcast=self.broadcast)
        self.music = MusicBridge(demo=self.demo, broadcast=self.broadcast)
        set_bridges(self.home, self.music, self)
        self.learner = Learner(self.memory, cfg["learner"])
        provider = (cfg["llm"].get("provider") or "auto").lower()
        self.brain = LLMBrain(cfg) if provider != "none" else None

        # fleet hub (core-side registry of all connected devices)
        self.hub: Optional[DeviceHub] = None
        if (cfg.get("fleet") or {}).get("enabled", False):
            self.hub = DeviceHub(self.memory, cfg, broadcast=self.broadcast)
            set_fleet_hub(self.hub)

        # prep engine (routines + habit-based getting-ready)
        self.prep: Optional[PrepEngine] = None
        if (cfg.get("prep") or {}).get("enabled", False):
            self.prep = PrepEngine(self.memory, cfg.get("prep", {}), cfg)
            self.prep.run_command = lambda cmd: self.handle(cmd)["reply"]
            set_prep_tool(self.prep)

        self.voice = None            # attached by run.py when voice is enabled
        self.voice_available = False
        self.history: deque = deque(maxlen=12)
        for m in self.memory.convo_tail(12):   # continuity across restarts
            self.history.append(m)
        self.state_name = "idle"
        self._sockets: set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._preps_shown: dict = {}  # key -> ts (10 min UI quiet)

    # ================= state / UI plumbing =================
    def set_event_loop(self, loop) -> None:
        self._loop = loop
        if self.hub:
            self.hub.set_loop(loop)

    def state(self) -> dict:
        return {
            "state": self.state_name,
            "llm": bool(self.brain and self.brain.available),
            "voice": bool(self.voice and self.voice_available),
            "fleet": bool(self.hub),
            "quiet": self._quiet(),
            "name": self.cfg["user"].get("name", "Boss"),
            "brain_label": self.brain.label if self.brain else "rule brain",
        }

    def hello_payload(self) -> dict:
        p = {"type": "hello"}
        p.update(self.state())
        p["facts"] = [f["text"] for f in self.memory.facts()]
        p["habits"] = self.memory.habits(min_uses=self.cfg["learner"].get("min_uses", 2))
        p["fleet"] = self.hub.summary() if self.hub else []
        p["activity"] = self.memory.activity_today()
        p["preps"] = self.prep.due_preps() if self.prep else []
        now_ts = time.time()
        p["calendar"] = self.memory.calendar_events(now_ts - 3600, now_ts + 86400)
        snap = self.markets.snapshot()
        p["markets"] = snap if snap.get("ok") else None
        p["home"] = self.home.state()
        p["music"] = self.music.status()
        p["scenes"] = self.prep.routine_names() if self.prep else []
        return p

    def attach(self, ws) -> None:
        self._sockets.add(ws)

    def detach(self, ws) -> None:
        self._sockets.discard(ws)

    def broadcast(self, payload: dict) -> None:
        """Thread-safe fan-out to every connected UI."""
        if not self._sockets or self._loop is None or not self._loop.is_running():
            return
        for ws in list(self._sockets):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(payload), self._loop)
            except Exception:
                self.detach(ws)

    def set_state(self, name: str) -> None:
        self.state_name = name
        self.broadcast({"type": "state", "state": name})

    def push_user_text(self, text: str) -> None:
        self.broadcast({"type": "user", "text": text})

    def push_level(self, value: float) -> None:
        self.broadcast({"type": "level", "value": value})

    # ================= quiet mode =================
    def _quiet_until(self) -> float:
        try:
            return float(self.memory.meta_get("quiet_until", "0"))
        except ValueError:
            return 0.0

    def _quiet(self) -> bool:
        return time.time() < self._quiet_until()

    def set_quiet(self, minutes: float) -> None:
        self.memory.meta_set("quiet_until", str(time.time() + minutes * 60))

    # ================= proactivity =================
    def maybe_proactive(self) -> Optional[dict]:
        if self._quiet():
            return None
        result = self.learner.proactive(name=self.cfg["user"].get("name", "Boss"))
        if result:
            self.broadcast({"type": "suggestion", **result})
        return result

    def maybe_preps(self) -> None:
        """Push due preps — as banners (ask) or execute them (auto)."""
        if not self.prep or self._quiet():
            return
        now = datetime.now()
        mode = (self.prep.cfg or {}).get("mode", "ask")
        for prep in self.prep.due_preps(now):
            last = self._preps_shown.get(prep["key"], 0)
            if now.timestamp() - last < 600:
                continue
            self._preps_shown[prep["key"]] = now.timestamp()
            action = prep.get("action", "")
            if mode == "auto" and action and not action.startswith("prep "):
                # the figurative "I've already got it ready" — no asking
                self.prep.mark(prep["key"], "done")

                def _run(a=action):
                    try:
                        r = self.handle(a)
                        self.broadcast({"type": "announce",
                                        "text": f"Prepped ahead: {r['reply']}"})
                    except Exception as exc:
                        self.broadcast({"type": "announce",
                                        "text": f"Prep didn't work ({exc})."})

                threading.Thread(target=_run, daemon=True).start()
            else:
                self.broadcast({"type": "prep", **prep})

    def maybe_sequence_suggestion(self) -> None:
        """Auto-learn: noticed you do A then B at the same time -> offer a routine."""
        if not self.prep or self._quiet():
            return
        cand = self._find_sequence()
        if not cand:
            return
        name, a_key, b_key, count, hour = cand
        key = f"seq:{name}"
        if self.memory.recently_suggested(key, cooldown_minutes=60 * 24):
            return
        self.memory.note_suggestion(key)
        actions = [a for a in (self._seq_action(a_key), self._seq_action(b_key))
                   if a]
        self.broadcast({
            "type": "routine_offer",
            "name": name,
            "actions": actions,
            "text": (f"I've noticed you usually {self._seq_phrase(a_key)} then "
                     f"{self._seq_phrase(b_key)} around {hour:02d}:00 "
                     f"({count} times). Want me to save that as routine "
                     f"'{name}'?"),
        })

    # ================= vision ("what am I looking at?") =================
    def see(self, device: str, question: str = "Describe what is on this screen."
            ) -> dict:
        """Capture a device screen and, if a vision-capable LLM is connected,
        actually describe it. Always honest about which happened."""
        if self.hub is None:
            return {"ok": False, "message": "Fleet isn't enabled."}
        r = self.hub.send(device, "screenshot")
        if not r.get("ok") or not r.get("url"):
            return {"ok": False,
                    "message": (r.get("message")
                                or f"couldn't capture {device}'s screen")}
        url = r["url"]
        path = os.path.join(self.hub.screenshot_dir(), os.path.basename(url))
        brain = self.brain
        if brain is not None and getattr(brain, "available", False) \
                and (self.cfg.get("llm") or {}).get("vision", True):
            import base64
            try:
                with open(path, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode()
            except OSError as exc:
                return {"ok": False, "message": f"capture unreadable: {exc}"}
            desc = brain.vision(b64, question)
            if desc:
                return {"ok": True, "url": url, "description": desc,
                        "vision": True}
        return {"ok": True, "url": url, "description": None, "vision": False,
                "message": ("Screen captured and on the overlay — but no "
                            "vision-capable LLM is connected yet, so I can't "
                            "describe it. Hook one up in config.yaml and I "
                            "will.")}

    # ================= markets / rate watchers =================
    def maybe_rate_alerts(self) -> None:
        """Fire any 'watch EURUSD below 1.05'-style alerts that have crossed."""
        if self._quiet():
            return
        alerts = self.memory.rate_alerts(active_only=True)
        if not alerts:
            return
        snap = self.markets.snapshot()
        if not snap.get("ok"):
            return
        prices = {}
        for bucket in ("pairs", "crypto", "indices"):
            for sym, row in (snap.get(bucket) or {}).items():
                prices[sym] = row["price"]
        for a in alerts:
            px = prices.get(a["pair"])
            if px is None:
                continue
            hit = px <= a["threshold"] if a["op"] == "below" else px >= a["threshold"]
            if not hit:
                continue
            self.memory.mark_rate_alert_hit(a["id"])
            text = (f"{a['pair']} just crossed {a['op']} {a['threshold']:g} — "
                    f"it's at {px:g} now.")
            if snap.get("simulated"):
                text += " (simulated feed)"
            self.broadcast({"type": "alert", "text": text})
            self.broadcast({"type": "announce", "text": "Rate alert, sir: " + text})

    # ================= calendar / meeting autopilot =================
    def maybe_meeting_prep(self) -> None:
        """As a meeting approaches: prep (auto or ask) + a 'starting soon' nudge."""
        if self._quiet():
            return
        lead = (self.cfg.get("calendar") or {}).get("lead_minutes", 10)
        now = time.time()
        for ev in self.memory.calendar_events(now, now + lead * 60 + 60):
            start_in = ev["start_ts"] - now
            if start_in < 0:
                continue
            title = ev["title"]
            if start_in <= 120:  # "it's starting" nudge, once
                key = f"meetnow:{ev['id']}"
                if not self.memory.recently_suggested(key, cooldown_minutes=60 * 24):
                    self.memory.note_suggestion(key)
                    self.broadcast({"type": "announce",
                                    "text": (f"Heads up, sir: {title} starts in "
                                             f"{max(1, int(start_in // 60))} minute.")})
            key = f"meetprep:{ev['id']}"
            if self.memory.recently_suggested(key, cooldown_minutes=60 * 24):
                continue
            self.memory.note_suggestion(key)
            mins = max(1, int(start_in // 60))
            routine_actions = (self.prep.resolve_routine("meeting")
                               if self.prep else None)
            mode = (self.prep.cfg or {}).get("mode", "ask") if self.prep else "ask"
            when = datetime.fromtimestamp(ev["start_ts"]).strftime("%H:%M")
            loc = ev.get("location") or ""
            label = (f"Meeting in {mins} min — {title} at {when}"
                     + (f" ({loc})" if loc else ""))
            if routine_actions and mode == "auto":
                self.broadcast({"type": "status",
                                "text": (f"Getting ready for {title} — "
                                         f"{len(routine_actions)} step(s).")})

                def _run(t=title, actions=routine_actions):
                    replies = []
                    for a in actions:
                        try:
                            replies.append(self.handle(a)["reply"])
                        except Exception as exc:
                            replies.append(f"(failed: {exc})")
                        time.sleep(0.5)
                    self.broadcast({"type": "announce",
                                    "text": f"Ready for {t}, sir."})

                threading.Thread(target=_run, daemon=True).start()
            else:
                self.broadcast({
                    "type": "prep",
                    "key": key,
                    "label": label + (" — run your 'meeting' routine?"
                                      if routine_actions else ""),
                    "when": when,
                    "action": "prep meeting" if routine_actions else "",
                })

    def seed_demo_calendar(self) -> None:
        """--demo: give today a shape (a near meeting, an afternoon 1:1, a deadline)."""
        now = time.time()
        start_of_day = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        if self.memory.calendar_events(start_of_day, now + 86400):
            return
        self.memory.calendar_add("Design sync (video)", now + 14 * 60,
                                 now + 34 * 60, location="Video call")
        self.memory.calendar_add("1:1 with Sam", now + 170 * 60,
                                 now + 190 * 60)
        self.memory.calendar_add("Ship the Q3 demo", now + 240 * 60)

    # ---- sequence detection helpers ----
    @staticmethod
    def _seq_action(key: str) -> str:
        tool, _, detail = key.partition(":")
        if tool in ("open_app", "active"):
            return f"open {detail}"
        if tool == "web_search":
            return f"search {detail}"
        if tool == "weather":
            return "weather"
        return ""

    @staticmethod
    def _seq_phrase(key: str) -> str:
        tool, _, detail = key.partition(":")
        if tool in ("open_app", "active"):
            return f"open {detail}"
        if tool == "web_search":
            return f"search for {detail}"
        if tool == "weather":
            return "check the weather"
        return key

    def _find_sequence(self):
        """Find a repeated A→B action pair (separate occasions) to propose."""
        if not self.prep:
            return None
        rows = self.memory.recent_actionable_events(days=7)
        if len(rows) < 4:
            return None
        routine_names = set(self.prep.routine_names())
        pairs: dict = {}
        for i in range(len(rows) - 1):
            x, y = rows[i], rows[i + 1]
            if y["ts"] - x["ts"] > 15 * 60 or x["key"] == y["key"]:
                continue
            pairs.setdefault((x["key"], y["key"]), []).append(y["ts"])
        best = None
        for (a_key, b_key), tss in pairs.items():
            tss.sort()
            clusters = 1
            for i in range(1, len(tss)):
                if tss[i] - tss[i - 1] > 15 * 60:
                    clusters += 1
            if clusters < 2:
                continue
            hour = datetime.fromtimestamp(tss[-1]).hour
            a_detail = a_key.partition(":")[2] or a_key
            b_detail = b_key.partition(":")[2] or b_key
            slug = re.sub(r"[^a-z0-9]+", "-",
                          f"{a_detail} then {b_detail}").strip("-")[:28] or "routine"
            if slug in routine_names:
                continue
            if best is None or clusters > best[3]:
                best = (slug, a_key, b_key, clusters, hour)
        return best

    # ================= fleet watchers =================
    def note_device_event(self, name: str, kind: str, data: dict) -> None:
        """Device event entry point (activity, services) from agents/sims."""
        if self.hub:
            self.hub.on_event(name, kind, data)

    def on_device_gone(self, name: str) -> None:
        auto_watch = (self.cfg.get("fleet") or {}).get("auto_watch", True)
        if not (auto_watch or self.memory.watcher_active(name)):
            return
        if self._quiet():
            return
        key = f"watch:{name}"
        if self.memory.recently_suggested(key, cooldown_minutes=10):
            return
        self.memory.note_suggestion(key)
        self.broadcast({
            "type": "alert",
            "text": f"{name} went offline — I'm keeping an eye out for it.",
            "action": f"run telemetry on {name}",
            "key": key,
        })

    def on_device_back(self, name: str, offline_secs: float) -> None:
        if offline_secs < 90 or self._quiet():
            return
        mins = max(1, int(offline_secs // 60))
        self.broadcast({"type": "announce",
                        "text": f"{name} is back online (was out about {mins} min)."})

    # ================= 'take care of it' =================
    def take_care(self, name: str) -> str:
        if not self.prep:
            return "Prep engine isn't enabled."
        actions = self.prep.resolve_routine(name)
        if actions is None:
            known = ", ".join(self.prep.routine_names()) or "none"
            return (f"Happy to — but I don't have a routine called '{name}'. "
                    f"Known: {known}.")

        def _run():
            self.broadcast({"type": "status",
                            "text": f"On it, sir. Taking care of '{name}' "
                                    f"— {len(actions)} step(s)."})
            replies = []
            for i, a in enumerate(actions, 1):
                self.broadcast({"type": "status",
                                "text": f"Step {i}/{len(actions)}: {a}"})
                try:
                    replies.append(self.handle(a)["reply"])
                except Exception as exc:
                    replies.append(f"({a} failed: {exc})")
                time.sleep(0.6)
            self.broadcast({"type": "status", "text": "All done, sir."})
            self.broadcast({"type": "reply",
                            "reply": "All done: " + " | ".join(replies)[:300],
                            "intent": "take_care", "tool": "fire_routine"})

        threading.Thread(target=_run, daemon=True).start()
        return "On it, sir. I'll take care of it and report back."

    # ================= auto-learning =================
    def _auto_learn(self, text: str) -> str:
        """Pick up facts from ordinary conversation. Returns a reply addendum."""
        t = text.strip().rstrip(".!?").lower()
        if not t or re.match(r"^(remember|keep in mind|what do you know)", t):
            return ""
        addendum = ""

        m = re.match(
            r"^(?:i|im) (?:really |always |usually |definitely )?(like|love|prefer|enjoy|want) (.+)$",
            t)
        if m:
            verb = _VERB_NOUNS[m.group(1)]
            fact = f"user {verb} {m.group(2).strip()}"
            if self.memory.remember(fact):
                addendum = " — and I've filed that under your notes."
            return addendum

        m = re.match(r"^(?:i|im) (?:really )?don't (?:like|want|enjoy) (.+)$", t)
        if m:
            if self.memory.remember(f"user dislikes {m.group(1).strip()}"):
                addendum = " — and I've filed that under your notes."
            return addendum

        m = re.match(r"^(?:i|im)'?m allergic to (.+)$", t)
        if m:
            if self.memory.remember(f"user is allergic to {m.group(1).strip()}"):
                addendum = " — and I'll keep that in mind."
            return addendum

        m = re.match(r"^(?:my name is|call me) (.+)$", t)
        if m:
            if self.memory.remember(f"user is called {m.group(1).strip()}"):
                addendum = " — noted."
            return addendum

        m = re.match(r"^(?:i|im) work (?:at|for) (.+)$", t)
        if m:
            if self.memory.remember(f"user works {m.group(1).strip()}"):
                addendum = " — and I've filed that under your notes."
            return addendum

        m = re.match(rf"^my (?:{'|'.join(_NOUNS)})(?: is| is called) ?(.+)$", t)
        if m:
            noun = t.split()[1]
            if self.memory.remember(f"user's {noun} is {m.group(1).strip()}"):
                addendum = " — and I've filed that under your notes."
            return addendum

        m = re.match(r"^(?:i|im) have a (deadline|meeting|appointment|exam|call) (.+)$", t)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            if self.memory.remember(f"user has a {kind}: {rest}"):
                addendum = " — filed. I'll keep it in mind when you brief me."
            if kind in ("meeting", "call", "appointment"):
                when = self._learned_event(kind, rest)
                if when:
                    addendum = f" — and I've put it on your calendar ({when})."
            return addendum

        # "I always open X at 9" -> auto-scheduled prep routine
        if re.match(r"^(?:i|im) (?:always|usually|normally) ", t):
            mt = re.search(r"\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?\b", t)
            if mt:
                h = int(mt.group(1))
                ap = mt.group(3)
                if ap == "pm" and h < 12:
                    h += 12
                if ap == "am" and h == 12:
                    h = 0
                head = re.sub(r"^(?:i|im) (?:always|usually|normally) ", "",
                              t[:mt.start()].strip())
                if re.match(r"^(open|play|search|check|run|start)\b", head):
                    name = re.sub(r"[^a-z0-9]+", "-", head).strip("-")[:28]
                    if name and not self.memory.routine_exists(name):
                        self.memory.save_routine(name, [head], "auto", f"{h:02d}:00")
                        addendum = (f" — understood. I'll have that ready at "
                                    f"{h:02d}:00 every day, and you can fire it "
                                    f"any time with 'prep {name}'.")
        return addendum

    def _learned_event(self, kind: str, rest: str):
        """'with priya at 4 pm tomorrow' -> calendar event; returns a time label."""
        m = re.search(r"\b(?:at|by)\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?\b", rest)
        if not m:
            return None
        h = int(m.group(1))
        ap = m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        minute = int(m.group(2) or 0)
        day = datetime.now()
        tomorrow = "tomorrow" in rest
        if not tomorrow and (h < day.hour or (h == day.hour and minute <= day.minute)):
            tomorrow = True  # that time already passed — assume tomorrow
        if tomorrow:
            day = day + timedelta(days=1)
        when = day.replace(hour=h, minute=minute, second=0,
                           microsecond=0).timestamp()
        no_time = re.sub(r"\b(?:at|by)\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?\b",
                         "", rest)
        no_time = re.sub(r"\b(tomorrow|today)\b", "", no_time).strip()
        mw = re.search(r"with\s+([a-z0-9\- ]+)$", no_time)
        who = mw.group(1).strip() if mw else ""
        leftover = no_time
        if who:
            leftover = no_time[:no_time.rfind("with")].strip(" -—")
        titles = {"meeting": "Meeting", "call": "Call",
                  "appointment": "Appointment", "deadline": "Deadline",
                  "task": "Task", "event": "Event"}
        title = titles.get(kind, "Event")
        if who:
            title += " with " + who.title()
        if leftover:
            title += ": " + leftover.title()
        dur = 3600 if kind in ("meeting", "event") else 1800
        self.memory.calendar_add(title, when, when + dur)
        return (datetime.fromtimestamp(when).strftime("%H:%M")
                + (" (tomorrow)" if tomorrow else ""))

    # ================= briefings =================
    def brief(self) -> str:
        now = datetime.now()
        name = self.cfg["user"].get("name", "Boss")
        h = now.hour
        period = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
        lines = [f"Here's your {period} brief, {name}. "
                 f"It's {now:%H:%M} on {now:%A, %d %B}."]
        today = self.memory.activity_today(3)
        if today:
            top = today[0]
            extra = f" across {len(today)} apps" if len(today) > 1 else ""
            lines.append(f"You've been at it for {top['seconds'] // 60} min in "
                         f"{top['app']}{extra} so far today.")
        nxt = self.memory.calendar_next(horizon_s=86400)
        if nxt:
            now_ts = now.timestamp()
            t_label = datetime.fromtimestamp(nxt["start_ts"]).strftime("%H:%M")
            mins = int((nxt["start_ts"] - now_ts) // 60)
            if mins < 0:
                lines.append(f"In progress: {nxt['title']}.")
            elif mins < 60:
                lines.append(f"Next: {nxt['title']} in {mins} min ({t_label}).")
            else:
                lines.append(f"Next: {nxt['title']} at {t_label} "
                             f"({mins // 60} h {mins % 60:02d} min from now).")
            day_end = now.replace(hour=23, minute=59, second=59).timestamp()
            later = [e for e in self.memory.calendar_events(now_ts + 60, day_end + 1)
                     if e["id"] != nxt["id"]][:3]
            if later:
                bits = ", ".join(
                    datetime.fromtimestamp(e["start_ts"]).strftime("%H:%M") + " "
                    + e["title"] for e in later)
                lines.append("Later today: " + bits + ".")
        if self.hub:
            devs = self.hub.summary()
            if devs:
                up = sum(1 for d in devs if d["online"])
                bits = []
                for d in devs[:5]:
                    t = d.get("telemetry") or {}
                    s = d["name"]
                    if d["online"] and t:
                        extra = []
                        for k in ("cpu_pct", "ram_pct", "disk_pct", "battery_pct"):
                            if k in t:
                                extra.append(f"{k.replace('_pct', '')} {t[k]}%")
                        s += (" — " + ", ".join(extra)) if extra else " — up"
                    else:
                        s += f" — OFFLINE {d['seen_ago']}s"
                    bits.append(s)
                lines.append(f"Fleet: {up}/{len(devs)} online — " + "; ".join(bits) + ".")
        if self.prep:
            habits = self.memory.habits(min_uses=2)
            upcoming = [x for x in habits
                        if x["weekday"] == now.weekday() and x["hour"] > now.hour][:3]
            if upcoming:
                later = ", ".join(f"{x['hour']:02d}:00 usually {x['detail'] or x['tool']}"
                                  for x in upcoming)
                lines.append(f"Later today: {later}.")
            routines = self.prep.routine_names()
            if routines:
                lines.append("Routines ready: " + ", ".join(routines)
                             + ". Say 'prep " + routines[0] + "' to fire one, "
                             "or 'take care of " + routines[0] + "' and I'll handle it.")
        snap = self.markets.snapshot()
        if snap.get("ok"):
            bits = []
            for sym, row in list((snap.get("pairs") or {}).items())[:3]:
                bits.append(f"{sym} {row['price']:g} ({row['chg_pct']:+.1f}%)")
            for sym, row in list((snap.get("crypto") or {}).items())[:1]:
                bits.append(f"{sym} {row['price']:,.0f}")
            tag = " [sim feed]" if snap.get("simulated") else ""
            if bits:
                lines.append("Markets" + tag + ": " + ", ".join(bits) + ".")
        hs = self.home.state()
        if hs.get("ok"):
            on = [n for n, l in (hs.get("lights") or {}).items() if l.get("on")]
            bits = [f"lights on: {', '.join(on) or 'none'}"]
            bits.append("TV " + ("on" if (hs.get("tv") or {}).get("on") else "off"))
            bits.append(f"climate {(hs.get('climate') or {}).get('target', 0):g}°C")
            tag = " [sim home]" if hs.get("simulated") else ""
            lines.append("Home" + tag + ": " + ", ".join(bits) + ".")
        ms = self.music.status()
        if ms.get("ok") and ms.get("playing"):
            lines.append(f"Now playing: {ms.get('track')}.")
        try:
            from .tools.web import news as _news_tool
            items = _news_tool()["items"]
            if items:
                top = items[0]["title"]
                lines.append(f"Top headline: {top}.")
        except Exception:  # noqa: BLE001 — news is optional garnish
            pass
        facts = self.memory.facts(2)
        if facts:
            lines.append("On file: " + "; ".join(f["text"] for f in facts) + ".")
        return " ".join(lines)

    # ================= core =================
    def handle(self, text: str) -> dict:
        """Run one user request through the best available brain.

        Bulletproof by design: a bug anywhere becomes a graceful reply,
        never a dead connection.
        """
        self.history.append({"role": "user", "content": text})
        self.memory.log_convo("user", text)
        try:
            if self.brain is not None and self.brain.available:
                try:
                    reply = self.brain.chat(list(self.history),
                                            self._memory_block(text))
                    intent = "llm"
                    tool = detail = ""
                except Exception as exc:
                    log.warning("LLM failed (%s) — using rule brain.", exc)
                    reply, intent, tool, detail = rule_respond(text, self.cfg,
                                                               self.memory, self)
            else:
                reply, intent, tool, detail = rule_respond(text, self.cfg,
                                                           self.memory, self)
        except Exception as exc:
            log.exception("handle() crashed on %r", text)
            reply = (f"Something glitched on my end ({exc.__class__.__name__}). "
                     "Try again, or say 'help' for what I can do.")
            intent = tool = detail = "error"

        # auto-learn from ordinary conversation (rule brain only — the LLM
        # brain files facts itself via its remember_fact tool)
        if intent not in ("llm", "error"):
            addendum = self._auto_learn(text)
            if addendum:
                reply = ("Got it" if intent == "chitchat" else reply) + addendum

        # first greeting of the day gets a compact brief appended
        today = datetime.now().strftime("%Y-%m-%d")
        if intent == "greet" and self.memory.meta_get("last_greet_day") != today:
            self.memory.meta_set("last_greet_day", today)
            try:
                reply = reply + " " + self.brief()
            except Exception:
                pass

        self.history.append({"role": "assistant", "content": reply})
        self.memory.log_convo("assistant", reply)
        try:
            self.learner.on_interaction(text, intent, tool or intent, detail)
        except Exception:
            log.exception("learner failed")
        return {"reply": reply, "intent": intent, "tool": tool}

    # ================= demo seeding (--demo only) =================
    def seed_demo_history(self) -> None:
        """Pretend the user had two work sessions earlier today, so the
        sequence-learner has something to notice."""
        now = datetime.now()
        for hh, mm in ((9, 0), (10, 30)):
            if hh > now.hour:
                continue
            base = now.replace(hour=hh, minute=mm, second=0).timestamp()
            self.memory.log_event("open vscode", "open", "open_app",
                                  "vs code", ts=base)
            self.memory.log_event("open terminal", "open", "open_app",
                                  "terminal", ts=base + 180)

    def _memory_block(self, text: str) -> str:
        """Context injected into the LLM: memories, habits, fleet, activity."""
        lines = []
        facts = self.memory.recall(text, k=3)
        if facts:
            lines.append("Relevant memories about the user:\n"
                         + "\n".join(f"- {f}" for f in facts))
        all_facts = self.memory.facts()
        if all_facts and len(all_facts) <= 8:
            lines.append("Known facts about the user: "
                         + "; ".join(f["text"] for f in all_facts))
        habits = self.memory.matches_now(window_hours=1)
        if habits:
            labels = sorted({h["tool"] + (f" {h['detail']}" if h["detail"] else "")
                             for h in habits})
            lines.append("The current time matches a learned habit: " + ", ".join(labels))
        if self.hub:
            devs = self.hub.summary()
            if devs:
                desc = "; ".join(
                    f"{d['name']} ({d['os']}, {'online' if d['online'] else 'offline'}"
                    + (f", cpu {d['telemetry'].get('cpu_pct')}%"
                       if d.get("telemetry", {}).get("cpu_pct") is not None else "")
                    + ")" for d in devs[:6])
                lines.append("Fleet devices: " + desc + ". You watch every device "
                             "and alert when one goes offline.")
        today = self.memory.activity_today(3)
        if today:
            desc = "; ".join(f"{a['app']} {a['seconds'] // 60} min" for a in today)
            lines.append("User's activity today: " + desc + ".")
        if self.prep:
            due = self.prep.due_preps()
            if due:
                lines.append("Preps due right now: "
                             + "; ".join(p["label"] for p in due) + ".")
            routines = self.prep.routine_names()
            if routines:
                lines.append("Named routines: " + ", ".join(routines)
                             + " (fire with fire_routine, or 'take care of X' "
                             "to run one in the background).")
        nxt = self.memory.calendar_next(horizon_s=86400)
        if nxt:
            t_label = datetime.fromtimestamp(nxt["start_ts"]).strftime("%H:%M")
            loc = f" ({nxt['location']})" if nxt.get("location") else ""
            lines.append(f"Calendar — next: {nxt['title']} at {t_label}{loc}. "
                         "Use calendar_today / calendar_add / calendar_cancel "
                         "for the rest of the day.")
        snap = self.markets.snapshot()
        if snap.get("ok"):
            bits = [f"{s} {r['price']:g}" for s, r in
                    list((snap.get("pairs") or {}).items())[:4]]
            bits += [f"{s} {r['price']:,.0f}" for s, r in
                     list((snap.get("crypto") or {}).items())[:2]]
            sim = " (SIMULATED demo feed — say so if asked)" \
                if snap.get("simulated") else ""
            lines.append("Markets now" + sim + ": " + ", ".join(bits) + ". "
                         "Tools: market_snapshot, convert_currency, set_rate_alert.")
        if self._quiet():
            lines.append("Quiet mode is ON — no proactive suggestions.")
        return "\n\n".join(lines)
