"""The SELF engine — JARVIS watching, scoring and rewriting *itself*.

Nothing here is theatre. Every turn is journaled; the user's own follow-ups
(thanks / "no, I said…" / repeating themselves) become reward signals; repeated
misunderstandings that the user later rephrases are mined into permanent
self-taught alias rules; habits you repeat across days become self-created
scheduled routines; suggestion aggressiveness is tuned from your acceptance
rate; flaky tools are marked degraded and skipped until they recover.

And it can explain itself: "why did you say that?" traces the real decision.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional

log = logging.getLogger("jarvis.self")

_POS = ("thanks", "thank you", "cheers", "perfect", "nice", "great",
        "good bot", "love it", "ta")
_NEG = ("no ", "nope", "not that", "wrong", "again", "i said", "stop it",
        "that's not")
_WORD = re.compile(r"[a-z0-9']+")
# intents worth turning into self-created scheduled routines
_ROUTINE_WORTHY = {"brief", "prep", "play", "lights", "markets", "news"}


def _tok(s: str) -> set:
    return {w for w in _WORD.findall((s or "").lower()) if len(w) > 2}


class SelfEngine:
    def __init__(self, memory, cfg: dict,
                 broadcast: Optional[Callable] = None):
        scfg = (cfg or {}).get("self", {}) or {}
        self.memory = memory
        self.enabled = bool(scfg.get("enabled", True))
        self.every = max(0.5, float(scfg.get("tune_every_minutes", 5))) * 60
        self.alias_min = int(scfg.get("alias_min_uses", 2))
        self.routine_days = int(scfg.get("routine_min_days", 3))
        self._broadcast = broadcast or (lambda p: None)
        self._last_tick = 0.0
        self._learned_announced: set = set()

    # ---------------- per-turn ----------------
    def on_turn(self, text: str, intent: str, tool: str, detail: str,
                ok: bool, latency: float) -> None:
        """Score the PREVIOUS turn from this user message, then journal this one."""
        if not self.enabled:
            return
        prev = self.memory.last_journal()
        sig = self._signal(text, prev)
        if sig and prev:
            self.memory.set_journal_signal(prev["id"], sig)
        self.memory.log_journal(text, intent, tool, detail, ok, latency)

    def _signal(self, text: str, prev: Dict) -> int:
        t = (text or "").strip().lower()
        if not prev:
            return 0
        if t.startswith(_POS):
            return 1
        if t.startswith(_NEG):
            return -1
        if prev.get("ts") and time.time() - prev["ts"] < 120:
            a, b = _tok(t), _tok(prev.get("text", ""))
            if a and b and len(a & b) / min(len(a), len(b)) > 0.7 \
                    and t != prev.get("text", "").strip().lower():
                return -1  # they repeated themselves — I missed it
        return 0

    # ---------------- periodic self-improvement ----------------
    def tick(self, force: bool = False) -> List[str]:
        """Run the self-improvement pass; returns announcements."""
        if not self.enabled:
            return []
        now = time.time()
        if not force and now - self._last_tick < self.every:
            return []
        self._last_tick = now
        notes: List[str] = []
        notes += self._mine_aliases()
        notes += self._mine_routines()
        notes += self._tune_proactivity()
        notes += self._mark_degraded()
        for n in notes:
            self._broadcast({"type": "announce", "text": n})
        if notes:
            self._broadcast({"type": "self", **self.stats()})
        return notes

    def _mine_aliases(self) -> List[str]:
        """Fallback phrase + user's rephrase within 3 min, repeated => alias."""
        rows = self.memory.journal_since(time.time() - 7 * 86400)
        pairs: Counter = Counter()
        canon: Dict[str, str] = {}
        for i, r in enumerate(rows):
            if r["intent"] != "chitchat":
                continue
            for nxt in rows[i + 1:i + 4]:
                if nxt["intent"] in ("chitchat", "error", ""):
                    continue
                if nxt["ts"] - r["ts"] > 180:
                    break
                p = r["text"].strip().lower()
                c = nxt["text"].strip().lower()
                if p and c and p != c:
                    pairs[(p, c)] += 1
                    canon[p] = c
                break
        notes = []
        for (p, c), n in pairs.items():
            if n >= self.alias_min and self.memory.self_rule_for(p) is None \
                    and p not in self._learned_announced:
                if self.memory.add_self_rule(p, c):
                    self._learned_announced.add(p)
                    note = (f"I've taught myself something: '{p}' now means "
                            f"'{c}'. Say 'unlearn {p}' if I got that wrong.")
                    notes.append(note)
        return notes

    def _mine_routines(self) -> List[str]:
        """Same request, same hour, on N different days => self-created routine."""
        rows = [r for r in self.memory.journal_all(4000)
                if r["intent"] in _ROUTINE_WORTHY and r["ok"]]
        by_key: Dict[tuple, set] = defaultdict(set)
        hours: Dict[tuple, int] = {}
        for r in rows:
            day = time.strftime("%Y-%m-%d", time.localtime(r["ts"]))
            hour = time.localtime(r["ts"]).tm_hour
            key = (r["intent"], (r["detail"] or "").lower())
            by_key[key].add(day)
            hours[key] = hour
        notes = []
        for key, days in by_key.items():
            if len(days) < self.routine_days:
                continue
            intent, detail = key
            slug = f"auto-{intent}" + (f"-{detail.replace(' ', '-')}" if detail else "")
            slug = re.sub(r"[^a-z0-9\-]", "", slug)[:40]
            if self.memory.routine_exists(slug):
                continue
            cmd = detail or intent
            schedule = f"{hours[key]:02d}:00"
            if self.memory.save_routine(slug, [cmd], source="self",
                                        schedule=schedule):
                note = (f"I noticed you ask for '{cmd}' around {schedule} most "
                        f"days — I've made that automatic. Say 'prep {slug}' "
                        f"any time, or 'cancel routine {slug}' to stop me.")
                notes.append(note)
        return notes

    def _tune_proactivity(self) -> List[str]:
        rows = self.memory.journal_since(time.time() - 7 * 86400, 600)
        pos = sum(1 for r in rows if r["signal"] == 1)
        neg = sum(1 for r in rows if r["signal"] == -1)
        if pos + neg == 0:
            return []
        neg_rate = neg / (pos + neg)
        mult = round(min(3.0, max(0.5, 0.75 + 2.5 * neg_rate)), 2)
        old = self.memory.tune_get("proactive_cooldown_mult", "1.0")
        if abs(float(old) - mult) >= 0.25:
            self.memory.tune_set("proactive_cooldown_mult", str(mult))
            why = ("you've been waving me off, so I'll suggest less often"
                   if mult > 1 else "you seem to like the initiative, "
                                    "so I'll tighten my cooldowns")
            return [f"Self-tuning: proactive cooldown ×{mult} — {why}."]
        return []

    def _mark_degraded(self) -> List[str]:
        rows = self.memory.journal_since(time.time() - 3600, 300)
        streak: Counter = Counter()
        notes = []
        for r in rows:  # oldest -> newest: streak ends at the latest turn
            tool = r["tool"] or r["intent"]
            if not r["ok"]:
                streak[tool] += 1
            else:
                streak[tool] = 0
        for tool, n in streak.items():
            key = f"degraded:{tool}"
            if n >= 3 and not self.memory.tune_get(key):
                self.memory.tune_set(key, str(time.time() + 600))
                notes.append(f"{tool} keeps failing — I've marked it degraded "
                             f"for 10 minutes and I'll retry after.")
            elif n == 0 and self.memory.tune_get(key):
                self.memory.tune_set(key, "")
        return notes

    # ---------------- introspection ----------------
    def stats(self) -> dict:
        rows = self.memory.journal_since(time.time() - 7 * 86400, 2000)
        total = len(rows)
        fb = sum(1 for r in rows if r["intent"] == "chitchat")
        err = sum(1 for r in rows if not r["ok"])
        pos = sum(1 for r in rows if r["signal"] == 1)
        neg = sum(1 for r in rows if r["signal"] == -1)
        lat = [r["latency"] for r in rows if r["latency"]]
        top = Counter(r["intent"] for r in rows if r["intent"] != "chitchat")
        return {
            "turns": total,
            "fallback_pct": round(100 * fb / total, 1) if total else 0.0,
            "error_pct": round(100 * err / total, 1) if total else 0.0,
            "praise": pos, "corrections": neg,
            "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else 0.0,
            "top_intents": top.most_common(5),
            "self_rules": self.memory.self_rules_all(),
            "tunes": self.memory.tunes_all(),
        }

    def explain(self) -> str:
        row = self.memory.last_journal()
        if not row:
            return "I haven't done anything yet this session — nothing to explain."
        alias = self.memory.self_rule_for(row["text"])
        how = (f"I recognised '{row['text']}' as something I taught myself "
               f"(it maps to '{alias['canon']}')" if alias else
               f"I matched it to intent '{row['intent']}'")
        sig = {1: " You seemed happy with it.",
               -1: " You corrected me afterwards — noted, and I've weighed it "
                   "into my tuning.",
               0: ""}[row["signal"]]
        tool = f" It ran tool '{row['tool']}'" if row["tool"] else ""
        ok = "" if row["ok"] else " (it errored, and I said so honestly)"
        return (f"Last turn: you said \"{row['text']}\". {how};{tool} in "
                f"{row['latency']:.0f} ms{ok}.{sig}")
