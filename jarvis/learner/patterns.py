"""The learning engine: turns your usage log into
"I know what you need, and I know when".
"""
from __future__ import annotations

from typing import Dict, Optional

HABIT_VERBS = {
    "open_app": "open {detail}",
    "web_search": "search for {detail}",
    "weather": "check the weather",
    "set_volume": "adjust the volume",
    "system_stats": "check laptop health",
    "fire_routine": "run the {detail} routine",
    "brief": "get your brief",
}

# When the user taps "DO IT" on a proactive suggestion, this gets sent.
HABIT_ACTIONS = {
    "open_app": "open {detail}",
    "web_search": "search {detail}",
    "weather": "weather",
    "fire_routine": "prep {detail}",
    "brief": "brief me",
}

GREETINGS = {
    "morning": ("Good morning, {name}. It's about the time you usually {verb} — "
                "want me to get on it?"),
    "afternoon": ("Just a heads-up, {name}: this is usually your time to {verb}. "
                  "Shall I?"),
    "evening": ("Evening, {name}. You tend to {verb} around now — want me to?"),
}


class Learner:
    def __init__(self, memory, learner_cfg: dict):
        self.memory = memory
        self.cfg = learner_cfg

    def on_interaction(self, text: str, intent: str, tool: str, detail: str = "") -> None:
        """Log every request — this is the raw material of learning."""
        self.memory.log_event(text, intent, tool, detail)

    def proactive(self, name: str = "Boss") -> Optional[Dict[str, str]]:
        """If the current time matches a learned habit, return a suggestion."""
        if not self.cfg.get("proactive", True):
            return None
        window = int(self.cfg.get("window_hours", 1))
        for h in self.memory.matches_now(window_hours=window):
            key = f"{h['tool']}:{h['detail']}:{h['weekday']}:{h['hour']}"
            mult = float(self.memory.tune_get("proactive_cooldown_mult", "1.0")
                         or 1.0)
            if self.memory.recently_suggested(key, cooldown_minutes=360 * mult):
                continue
            verb = self._phrase(HABIT_VERBS.get(h["tool"]), h)
            action = self._phrase(HABIT_ACTIONS.get(h["tool"]), h, bare=True)
            hour = h["hour"]
            period = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
            self.memory.note_suggestion(key)
            return {
                "text": GREETINGS[period].format(name=name, verb=verb),
                "action": action,
                "tool": h["tool"],
            }
        return None

    @staticmethod
    def _phrase(template: Optional[str], h: dict, bare: bool = False) -> str:
        if template and "{detail}" in template:
            return template.format(detail=h["detail"] or "it")
        base = template or ("use " + h["tool"] if bare else f"use '{h['tool']}'")
        if h["detail"]:
            base = f"{base} ({h['detail']})" if not bare else f"{base} {h['detail']}"
        return base
