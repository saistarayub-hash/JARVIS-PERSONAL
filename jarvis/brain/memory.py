"""Persistent memory: long-term facts + interaction log + habit learning.

Everything lives in a single SQLite file (data/memory.db) on the user's
machine. Nothing leaves the laptop.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "my", "me", "i",
    "im", "you", "your", "is", "are", "was", "were", "be", "been", "am", "do",
    "does", "did", "will", "would", "can", "could", "should", "to", "of", "in",
    "on", "for", "with", "about", "at", "by", "from", "it", "its", "this",
    "that", "these", "those", "there", "here", "when", "what", "who", "how",
    "why", "please", "just", "really", "very", "now", "today", "get", "want",
    "need", "like", "tell", "show", "give", "around", "every", "day", "time",
}

# Tools/intents that don't represent a repeatable *habit* (small talk, one-offs).
_NON_HABIT_TOOLS = {"", "llm", "chitchat", "remember_fact", "joke",
                    "get_time", "get_date", "math", "help",
                    "greet", "know_me", "suggestions", "stop", "time", "date",
                    "error", "brief", "prep", "run_remote", "fleet", "device"}


def _tokens(text: str) -> List[str]:
    return [t for t in _WORD.findall(text.lower()) if len(t) > 1 and t not in _STOP]


class Memory:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        parent = os.path.dirname(self.db_path)
        os.makedirs(parent, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # One connection, many threads (UI, voice, agents, timers) — lock it.
        self._lock = threading.RLock()
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS facts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL UNIQUE,
                    tags TEXT DEFAULT '',
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, text TEXT, intent TEXT, tool TEXT, detail TEXT,
                    hour INTEGER, weekday INTEGER
                );
                CREATE TABLE IF NOT EXISTS suggestions_log(
                    key TEXT PRIMARY KEY, last_ts REAL
                );
                CREATE TABLE IF NOT EXISTS devices(
                    name TEXT PRIMARY KEY, os TEXT, meta TEXT, last_seen REAL
                );
                CREATE TABLE IF NOT EXISTS activity(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, app TEXT, title TEXT, seconds REAL
                );
                CREATE TABLE IF NOT EXISTS prep_log(
                    key TEXT, day TEXT, status TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS routines(
                    name TEXT PRIMARY KEY,
                    actions_json TEXT NOT NULL,
                    source TEXT DEFAULT 'config',
                    schedule TEXT,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS watchers(
                    device TEXT PRIMARY KEY,
                    active INTEGER DEFAULT 1,
                    since REAL
                );
                CREATE TABLE IF NOT EXISTS meta(
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS calendar(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start_ts REAL NOT NULL,
                    end_ts REAL,
                    location TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS rate_alerts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    op TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at REAL,
                    hit_at REAL
                );
                CREATE TABLE IF NOT EXISTS convo(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ts REAL
                );
                CREATE TABLE IF NOT EXISTS journal(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, text TEXT, intent TEXT, tool TEXT, detail TEXT,
                    ok INTEGER, latency REAL, signal INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS self_rules(
                    pattern TEXT PRIMARY KEY,
                    canon TEXT NOT NULL,
                    uses INTEGER DEFAULT 0,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS self_tune(
                    key TEXT PRIMARY KEY, value TEXT, updated REAL
                );
                CREATE TABLE IF NOT EXISTS tasks(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    due_ts REAL,
                    repeat TEXT DEFAULT '',
                    done INTEGER DEFAULT 0,
                    fired INTEGER DEFAULT 0,
                    created REAL
                );
                CREATE TABLE IF NOT EXISTS digest (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT,
                    kind TEXT, text TEXT, delivered INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS push_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, channel TEXT,
                    text TEXT, status TEXT, simulated INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS web_watches(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    keyword TEXT DEFAULT '',
                    interval_s REAL DEFAULT 600,
                    last_hash TEXT DEFAULT '',
                    kw_seen INTEGER DEFAULT 0,
                    last_check REAL DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    note TEXT DEFAULT ''
                );
                """
            )
            self.db.commit()

    # ---------- facts (what JARVIS remembers about you) ----------
    def remember(self, text: str, tags: str = "") -> bool:
        text = " ".join(text.split())
        if not text:
            return False
        try:
            with self._lock:
                self.db.execute(
                    "INSERT INTO facts(text, tags, created_at) VALUES (?,?,?)",
                    (text, tags, time.time()))
                self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def forget(self, text: str) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM facts WHERE text = ?", (text,))
            self.db.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        with self._lock:
            cur = self.db.execute("DELETE FROM facts")
            self.db.commit()
        return cur.rowcount

    def facts(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT text, tags, created_at FROM facts "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def recall(self, query: str, k: int = 3) -> List[str]:
        """Naive keyword-overlap retrieval — good enough for personal facts."""
        q = set(_tokens(query))
        if not q:
            return []
        scored = []
        for f in self.facts():
            overlap = q & set(_tokens(f["text"]))
            if overlap:
                score = len(overlap) / math.sqrt(len(f["text"].split()) + 1)
                scored.append((score, f["text"]))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [t for _, t in scored[:k]]

    # ---------- events (everything you ask for, timestamped) ----------
    def log_event(self, text: str, intent: str, tool: str, detail: str = "",
                  ts: float | None = None) -> None:
        now = datetime.now()
        with self._lock:
            self.db.execute(
                "INSERT INTO events(ts, text, intent, tool, detail, hour, weekday) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts if ts is not None else time.time(), text[:300], intent,
                 tool, (detail or "")[:200], now.hour, now.weekday()))
            self.db.commit()

    def recent_actionable_events(self, days: int = 7) -> List[Dict[str, Any]]:
        """Chronological user-actionable events for sequence learning."""
        since = time.time() - days * 86400
        tools = ("open_app", "web_search", "active", "weather", "set_volume")
        ph = ",".join("?" * len(tools))
        with self._lock:
            rows = self.db.execute(
                f"SELECT ts, tool, detail FROM events WHERE ts >= ? AND tool IN ({ph}) "
                "ORDER BY ts ASC", (since, *tools)).fetchall()
        return [{"ts": r["ts"], "tool": r["tool"],
                 "detail": (r["detail"] or "").lower(),
                 "key": f"{r['tool']}:{(r['detail'] or '').lower()}"}
                for r in rows]

    def habits(self, min_uses: int = 2) -> List[Dict[str, Any]]:
        """Aggregate the event log into (tool, detail, weekday, hour) habits.

        Weighted by recency: a habit from 3 weeks ago counts for half as much
        as today's, so JARVIS adapts when your routine changes.
        """
        with self._lock:
            rows = self.db.execute(
                "SELECT tool, detail, weekday, hour, ts FROM events "
                "WHERE tool != ''").fetchall()
        now = time.time()
        weight: Dict[tuple, float] = {}
        count: Counter = Counter()
        for r in rows:
            if r["tool"] in _NON_HABIT_TOOLS:
                continue
            key = (r["tool"], (r["detail"] or "").lower(), r["weekday"], r["hour"])
            age_days = max(0.0, (now - r["ts"]) / 86400.0)
            weight[key] = weight.get(key, 0.0) + 0.5 ** (age_days / 14.0)
            count[key] += 1
        out = []
        for (tool, detail, weekday, hour), w in weight.items():
            c = count[(tool, detail, weekday, hour)]
            if c >= min_uses and w >= min_uses * 0.6:
                out.append({"tool": tool, "detail": detail, "weekday": weekday,
                            "hour": hour, "count": c, "weight": round(w, 2)})
        out.sort(key=lambda h: h["weight"], reverse=True)
        return out

    def matches_now(self, window_hours: int = 1) -> List[Dict[str, Any]]:
        """Habits whose weekday+hour window covers *right now*."""
        now = datetime.now()
        return [h for h in self.habits()
                if h["weekday"] == now.weekday()
                and abs(h["hour"] - now.hour) <= window_hours]

    # ---------- suggestion cooldowns ----------
    def recently_suggested(self, key: str, cooldown_minutes: float = 360) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT last_ts FROM suggestions_log WHERE key = ?",
                (key,)).fetchone()
        return bool(row and time.time() - row["last_ts"] < cooldown_minutes * 60)

    def note_suggestion(self, key: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO suggestions_log(key, last_ts) VALUES (?,?)",
                (key, time.time()))
            self.db.commit()

    # ---------- fleet devices ----------
    def upsert_device(self, name: str, os: str, meta_json: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO devices(name, os, meta, last_seen) VALUES (?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET os=excluded.os, meta=excluded.meta, "
                "last_seen=excluded.last_seen",
                (name, os, meta_json, time.time()))
            self.db.commit()

    def device_rows(self):
        with self._lock:
            return self.db.execute(
                "SELECT name, os, meta, last_seen FROM devices").fetchall()

    # ---------- activity (what you've been doing) ----------
    def log_activity(self, app: str, title: str, seconds: float) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO activity(ts, app, title, seconds) VALUES (?,?,?,?)",
                (time.time(), app, (title or "")[:120], seconds))
            self.db.commit()

    def activity_today(self, limit: int = 6) -> List[Dict[str, Any]]:
        since = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._lock:
            rows = self.db.execute(
                "SELECT app, SUM(seconds) AS secs, COUNT(*) AS sessions "
                "FROM activity WHERE ts >= ? AND app != '' "
                "GROUP BY app ORDER BY secs DESC LIMIT ?",
                (since, limit)).fetchall()
        return [{"app": r["app"], "seconds": int(r["secs"] or 0),
                 "sessions": r["sessions"]} for r in rows]

    # ---------- prep cooldowns ----------
    def prep_marked(self, key: str, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        day = now.strftime("%Y-%m-%d")
        with self._lock:
            row = self.db.execute(
                "SELECT status, ts FROM prep_log WHERE key=? AND day=? "
                "ORDER BY ts DESC LIMIT 1", (key, day)).fetchone()
        if not row:
            return False
        if row["status"] == "done":
            return True
        return (time.time() - row["ts"]) < 1800  # snoozed -> quiet 30 min

    def mark_prep(self, key: str, status: str, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._lock:
            self.db.execute(
                "INSERT INTO prep_log(key, day, status, ts) VALUES (?,?,?,?)",
                (key, now.strftime("%Y-%m-%d"), status, time.time()))
            self.db.commit()

    # ---------- routines (learned or user-defined) ----------
    def save_routine(self, name: str, actions: List[str],
                     source: str = "user", schedule: str | None = None) -> bool:
        import json as _json
        with self._lock:
            try:
                self.db.execute(
                    "INSERT INTO routines(name, actions_json, source, schedule, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (name, _json.dumps(actions), source, schedule, time.time()))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def routine_exists(self, name: str) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT 1 FROM routines WHERE name = ?", (name,)).fetchone()
        return bool(row)

    def routines_all(self) -> List[Dict[str, Any]]:
        import json as _json
        with self._lock:
            rows = self.db.execute(
                "SELECT name, actions_json, source, schedule FROM routines "
                "ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            try:
                actions = _json.loads(r["actions_json"] or "[]")
            except ValueError:
                actions = []
            out.append({"name": r["name"], "actions": actions,
                        "source": r["source"], "schedule": r["schedule"]})
        return out

    # ---------- watchers ("keep an eye on it") ----------
    def watch(self, device: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO watchers(device, active, since) VALUES (?,?,?)",
                (device, 1, time.time()))
            self.db.commit()

    def unwatch(self, device: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM watchers WHERE device = ?", (device,))
            self.db.commit()

    def watcher_active(self, device: str) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT active FROM watchers WHERE device = ?", (device,)).fetchone()
        return bool(row and row["active"])

    # ---------- misc key/value (quiet mode, last greeting, ...) ----------
    def meta_get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.db.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                (key, value))
            self.db.commit()

    # ---------- calendar ----------
    def calendar_add(self, title: str, start_ts: float, end_ts: float = 0.0,
                     location: str = "", url: str = "", notes: str = "") -> int:
        if not end_ts or end_ts <= start_ts:
            end_ts = start_ts + 3600
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO calendar(title, start_ts, end_ts, location, url, "
                "notes, created_at) VALUES (?,?,?,?,?,?,?)",
                (title, start_ts, end_ts, location or "", url or "",
                 (notes or "")[:500], time.time()))
            self.db.commit()
            return int(cur.lastrowid)

    def calendar_events(self, t0: float, t1: float) -> List[Dict[str, Any]]:
        """Events that START inside [t0, t1), sorted."""
        with self._lock:
            rows = self.db.execute(
                "SELECT id, title, start_ts, end_ts, location, url FROM calendar "
                "WHERE start_ts >= ? AND start_ts < ? ORDER BY start_ts ASC",
                (t0, t1)).fetchall()
        return [dict(r) for r in rows]

    def calendar_next(self, after_ts: float | None = None,
                      horizon_s: float = 86400) -> Dict[str, Any] | None:
        now = after_ts if after_ts is not None else time.time()
        rows = self.calendar_events(now, now + horizon_s)
        return rows[0] if rows else None

    def calendar_remove(self, title_contains: str,
                        before_ts: float | None = None) -> Dict[str, Any] | None:
        """Remove the next (soonest) event whose title matches. Returns it."""
        t0 = time.time()
        t1 = before_ts or t0 + 86400
        victim = None
        for ev in self.calendar_events(t0, t1):
            if title_contains.lower() in ev["title"].lower():
                victim = ev
                break
        if victim is None:
            return None
        with self._lock:
            self.db.execute("DELETE FROM calendar WHERE id = ?",
                            (victim["id"],))
            self.db.commit()
        return victim

    def calendar_count(self) -> int:
        with self._lock:
            row = self.db.execute("SELECT COUNT(*) FROM calendar").fetchone()
        return int(row[0])

    # ---------- rate alerts ("watch the rand below 19") ----------
    def add_rate_alert(self, pair: str, op: str, threshold: float) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO rate_alerts(pair, op, threshold, active, created_at) "
                "VALUES (?,?,?,?,?)", (pair, op, threshold, 1, time.time()))
            self.db.commit()
            return int(cur.lastrowid)

    def rate_alerts(self, active_only: bool = True) -> List[Dict[str, Any]]:
        q = ("SELECT id, pair, op, threshold, active FROM rate_alerts "
             + ("WHERE active = 1 " if active_only else "") + "ORDER BY id")
        with self._lock:
            rows = self.db.execute(q).fetchall()
        return [dict(r) for r in rows]

    def clear_rate_alerts(self, pair: str = "") -> int:
        with self._lock:
            if pair:
                cur = self.db.execute(
                    "DELETE FROM rate_alerts WHERE pair = ?", (pair,))
            else:
                cur = self.db.execute("DELETE FROM rate_alerts")
            self.db.commit()
        return cur.rowcount

    def mark_rate_alert_hit(self, alert_id: int) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE rate_alerts SET active = 0, hit_at = ? WHERE id = ?",
                (time.time(), alert_id))
            self.db.commit()

    # ---------- conversation memory (LLM continuity across restarts) ----------
    def log_convo(self, role: str, text: str, keep: int = 400) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO convo(role, text, ts) VALUES (?,?,?)",
                (role, (text or "")[:1200], time.time()))
            self.db.execute(
                "DELETE FROM convo WHERE id NOT IN "
                "(SELECT id FROM convo ORDER BY id DESC LIMIT ?)", (keep,))
            self.db.commit()

    def convo_tail(self, n: int = 12, max_age_h: float = 24) -> List[Dict[str, Any]]:
        since = time.time() - max_age_h * 3600
        with self._lock:
            rows = self.db.execute(
                "SELECT role, text FROM convo WHERE ts >= ? "
                "ORDER BY id DESC LIMIT ?", (since, n)).fetchall()
        return [{"role": r["role"], "content": r["text"]} for r in reversed(rows)]

    # ---------- self-model: decision journal, self-taught rules, tuning ----
    def log_journal(self, text: str, intent: str, tool: str, detail: str,
                    ok: bool, latency: float,
                    ts: float | None = None) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO journal(ts, text, intent, tool, detail, ok, latency) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts if ts is not None else time.time(), (text or "")[:300],
                 intent, tool, (detail or "")[:120], 1 if ok else 0, latency))
            self.db.commit()
            return int(cur.lastrowid)

    def set_journal_signal(self, jid: int, sig: int) -> None:
        with self._lock:
            self.db.execute("UPDATE journal SET signal = ? WHERE id = ?",
                            (sig, jid))
            self.db.commit()

    def last_journal(self) -> Dict[str, Any] | None:
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM journal ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def journal_since(self, since: float, limit: int = 400) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM journal WHERE ts >= ? ORDER BY id ASC LIMIT ?",
                (since, limit)).fetchall()
        return [dict(r) for r in rows]

    def journal_all(self, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM journal ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def add_self_rule(self, pattern: str, canon: str) -> bool:
        with self._lock:
            try:
                self.db.execute(
                    "INSERT INTO self_rules(pattern, canon, uses, created_at) "
                    "VALUES (?,?,0,?)", (pattern, canon, time.time()))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def self_rule_for(self, text: str) -> Dict[str, Any] | None:
        with self._lock:
            row = self.db.execute(
                "SELECT pattern, canon FROM self_rules WHERE pattern = ?",
                ((text or "").strip().lower(),)).fetchone()
        return dict(row) if row else None

    def bump_self_rule(self, pattern: str) -> None:
        with self._lock:
            self.db.execute("UPDATE self_rules SET uses = uses + 1 "
                            "WHERE pattern = ?", (pattern,))
            self.db.commit()

    def self_rules_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT pattern, canon, uses FROM self_rules "
                "ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def drop_self_rule(self, pattern: str) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM self_rules WHERE pattern = ?",
                                  (pattern.strip().lower(),))
            self.db.commit()
        return cur.rowcount > 0

    def tune_get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.db.execute(
                "SELECT value FROM self_tune WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def tune_set(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO self_tune(key, value, updated) "
                "VALUES (?,?,?)", (key, value, time.time()))
            self.db.commit()

    def tunes_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT key, value, updated FROM self_tune ORDER BY key").fetchall()
        return [dict(r) for r in rows]

    # ---------- tasks & reminders ----------
    def add_task(self, text: str, due_ts: float | None = None,
                 repeat: str = "") -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO tasks(text, due_ts, repeat, created) VALUES (?,?,?,?)",
                (text, due_ts, repeat or "", time.time()))
            self.db.commit()
            return int(cur.lastrowid)

    def tasks_open(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM tasks WHERE done = 0 ORDER BY "
                "CASE WHEN due_ts IS NULL THEN 1 ELSE 0 END, due_ts ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_task(self, ident) -> Dict[str, Any] | None:
        with self._lock:
            if str(ident).isdigit():
                row = self.db.execute(
                    "SELECT * FROM tasks WHERE id = ? AND done = 0",
                    (int(ident),)).fetchone()
            else:
                row = self.db.execute(
                    "SELECT * FROM tasks WHERE done = 0 AND lower(text) LIKE ? "
                    "ORDER BY id DESC LIMIT 1", (f"%{str(ident).lower()}%",)).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE tasks SET done = 1 WHERE id = ?",
                            (row["id"],))
            self.db.commit()
        return dict(row)

    def clear_done_tasks(self) -> int:
        with self._lock:
            cur = self.db.execute("DELETE FROM tasks WHERE done = 1")
            self.db.commit()
        return cur.rowcount

    def reschedule_task(self, tid: int, new_due: float, fired: int = 0) -> None:
        with self._lock:
            self.db.execute("UPDATE tasks SET due_ts = ?, fired = ? WHERE id = ?",
                            (new_due, fired, tid))
            self.db.commit()

    def mark_task_fired(self, tid: int) -> None:
        with self._lock:
            self.db.execute("UPDATE tasks SET fired = 1, done = 1 WHERE id = ?",
                            (tid,))
            self.db.commit()

    # ---------- web watchers ----------
    def add_web_watch(self, url: str, keyword: str = "",
                      interval_s: float = 600) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO web_watches(url, keyword, interval_s) VALUES (?,?,?)",
                (url, keyword or "", interval_s))
            self.db.commit()
            return int(cur.lastrowid)

    def web_watches(self, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM web_watches" + (" WHERE active = 1" if active_only else "")
        with self._lock:
            rows = self.db.execute(q).fetchall()
        return [dict(r) for r in rows]

    def drop_web_watch(self, url: str) -> int:
        with self._lock:
            cur = self.db.execute(
                "DELETE FROM web_watches WHERE url LIKE ?", (f"%{url}%",))
            self.db.commit()
        return cur.rowcount

    def update_web_watch(self, wid: int, last_hash: str, kw_seen: int,
                         note: str = "") -> None:
        with self._lock:
            self.db.execute(
                "UPDATE web_watches SET last_hash = ?, kw_seen = ?, "
                "last_check = ?, note = ? WHERE id = ?",
                (last_hash, kw_seen, time.time(), note, wid))
            self.db.commit()

    # ---------- v9: digest & push outbox ----------

    def digest_add(self, day: str, kind: str, text: str):
        self.db.execute("insert into digest (ts, day, kind, text) values (?,?,?,?)",
                           (time.time(), day, kind, text))
        self.db.commit()

    def digest_pending(self) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            "select ts, kind, text from digest where delivered = 0 order by ts").fetchall()
        return [dict(r) for r in rows]

    def digest_deliver(self) -> int:
        n = self.digest_pending_count()
        if n:
            self.db.execute("update digest set delivered = 1 where delivered = 0")
            self.db.commit()
        return n

    def digest_pending_count(self) -> int:
        r = self.db.execute("select count(*) from digest where delivered = 0").fetchone()
        return r[0] if r else 0

    def push_log(self, channel: str, text: str, status: str, simulated: bool = True):
        self.db.execute(
            "insert into push_log (ts, channel, text, status, simulated) values (?,?,?,?,?)",
            (time.time(), channel, text, status, int(simulated)))
        self.db.commit()

    def push_recent(self, limit: int = 6) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            "select ts, channel, text, status, simulated from push_log "
            "order by id desc limit ?", (limit,)).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        return out
