"""The prep engine — JARVIS getting itself ready *before* you ask.

Two sources:
1. Habits learned from usage: "you usually open spotify at 19:00" ->
   5 minutes earlier JARVIS offers (or auto-runs) the prep.
2. Explicit routines in config.yaml, either on-demand ("prep work") or
   scheduled ("morning" at 08:30 on weekdays).

A routine is just a list of plain commands, so routines can use ANY
capability: open apps, search, weather, even "run disk on web-01".
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

HABIT_PREP_VERBS = {
    "open_app": "open {detail}",
    "active": "work in {detail}",
    "web_search": "search for {detail}",
    "weather": "check the weather",
    "set_volume": "adjust the volume",
}


class PrepEngine:
    def __init__(self, memory, prep_cfg: dict, app_cfg: dict):
        self.memory = memory
        self.cfg = prep_cfg or {}
        self.app_cfg = app_cfg
        self.run_command: Optional[Callable[[str], str]] = None  # set by Jarvis

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def _action_for(self, tool: str, detail: str) -> Optional[str]:
        if tool in ("open_app", "active"):
            return f"open {detail}" if detail else None
        if tool == "web_search":
            return f"search {detail}" if detail else None
        if tool == "weather":
            return "weather"
        if tool == "set_volume":
            return f"volume {detail}" if detail else None
        return None

    def _label_for(self, tool: str, detail: str) -> str:
        template = HABIT_PREP_VERBS.get(tool, f"use '{tool}'")
        if "{detail}" in template:
            return template.format(detail=detail or "it")
        return f"{template} ({detail})" if detail else template

    def due_preps(self, now: Optional[datetime] = None) -> List[dict]:
        """Preps whose time window covers *now* (lead time included)."""
        now = now or datetime.now()
        out: List[dict] = []
        lead = int(self.cfg.get("lead_minutes", 5))
        catchup = int(self.cfg.get("catchup_minutes", 15))

        # 1) learned habits
        min_uses = int((self.app_cfg.get("learner") or {}).get("min_uses", 2))
        min_w = float(self.cfg.get("min_habit_weight", 2.0))
        for h in self.memory.habits(min_uses=min_uses):
            if h["weight"] < min_w or h["weekday"] != now.weekday():
                continue
            slot = now.replace(hour=h["hour"], minute=0, second=0, microsecond=0)
            if not (slot - timedelta(minutes=lead) <= now < slot + timedelta(minutes=catchup)):
                continue
            action = self._action_for(h["tool"], h["detail"])
            key = f"habit:{h['tool']}:{h['detail']}:{h['weekday']}:{h['hour']}"
            if action is None or self.memory.prep_marked(key, now):
                continue
            out.append({
                "key": key,
                "label": f"About your usual time to {self._label_for(h['tool'], h['detail'])} "
                         f"(~{h['hour']:02d}:00).",
                "action": action,
                "when": f"{h['hour']:02d}:00",
            })

        # 2) routines with a schedule (config-defined or auto-learned)
        for r in self.scheduled_routines():
            try:
                hh, mm = (int(x) for x in str(r["at"]).split(":"))
            except ValueError:
                continue
            days = [str(d).lower()[:3] for d in r.get("weekdays", [])]
            if days and now.strftime("%a").lower()[:3] not in days:
                continue
            slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not (slot - timedelta(minutes=lead) <= now < slot + timedelta(minutes=catchup)):
                continue
            key = f"routine:{r['name']}:{now:%Y-%m-%d}"
            if self.memory.prep_marked(key, now):
                continue
            out.append({
                "key": key,
                "label": f"Time for your '{r['name']}' routine.",
                "action": f"prep {r['name']}",
                "when": str(r["at"]),
            })
        return out

    def routine_names(self) -> List[str]:
        names = list((self.cfg.get("routines") or {}).keys())
        for r in self.memory.routines_all():
            if r["name"] not in names:
                names.append(r["name"])
        return names

    def resolve_routine(self, name: str) -> Optional[List[str]]:
        routines = self.cfg.get("routines") or {}
        if name in routines:
            return (routines[name] or {}).get("actions", [])
        for r in self.memory.routines_all():
            if r["name"] == name:
                return r["actions"]
        return None

    def fire(self, prep: dict) -> str:
        """Run a prep (one command or a whole routine) and return the report."""
        if self.run_command is None:
            return "Prep engine isn't wired up yet."
        commands = prep.get("actions") or [prep.get("action")]
        replies = []
        for cmd in commands:
            try:
                replies.append(self.run_command(cmd))
            except Exception as exc:  # noqa: BLE001
                replies.append(f"({cmd} failed: {exc})")
        return " ".join(replies)

    def fire_routine(self, name: str) -> str:
        actions = self.resolve_routine(name)
        if actions is None:
            known = ", ".join(self.routine_names()) or "none defined"
            return f"I don't have a routine called '{name}'. Known: {known}."
        return self.fire({"actions": actions, "routine_name": name})

    def scheduled_routines(self) -> List[dict]:
        """Routines (config + learned) that carry a time schedule."""
        out = []
        for name, r in (self.cfg.get("routines") or {}).items():
            if isinstance(r, dict) and r.get("at"):
                out.append({"name": name, "at": r["at"],
                            "weekdays": r.get("weekdays", []),
                            "actions": r.get("actions", [])})
        for r in self.memory.routines_all():
            if r.get("schedule"):
                out.append({"name": r["name"], "at": r["schedule"],
                            "weekdays": [], "actions": r["actions"]})
        return out

    def mark(self, key: str, status: str = "done") -> None:
        self.memory.mark_prep(key, status)
