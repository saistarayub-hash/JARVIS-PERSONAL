"""LLM brain through any OpenAI-compatible API.

Works with OpenAI, Ollama, LM Studio, vLLM, Groq... — anything that serves
POST /chat/completions. If nothing is reachable, JARVIS falls back to the
rule brain so you're never stuck.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional

import requests

from ..tools import execute, specs

SYSTEM_TEMPLATE = """You are JARVIS, a personal AI butler living on the user's laptop.
Personality: calm, precise, quietly witty British butler. You address the user as "{name}".
Style rules:
- Be concise: 1-3 sentences unless the user asks for detail. No filler, no exclamation marks.
- Use your tools to DO things, not just talk. If a tool reports an error, say so calmly and suggest the fix.
- Before answering anything personal, call recall_facts. If the user shares a lasting fact about themselves, call remember_fact.
- You have learned habits about the user's routine; use them to be helpful and proactive, never creepy.
- Chain tools when a request needs several steps (e.g. capture then describe, add event then prep).
- Current local time: {now}.
{manifest}
{memory_block}"""


def capability_manifest() -> str:
    """Auto-generated action space, so any OpenAI-compatible model instantly
    knows everything JARVIS can physically do on this install."""
    from .. import tools as _tools
    groups = [
        ("Laptop", ["open_app", "find_files", "set_volume", "system_stats",
                    "math", "web_search", "read_url", "news", "world_time",
                    "weather", "joke"]),
        ("Memory & learning", ["remember_fact", "recall_facts"]),
        ("Calendar", ["calendar_today", "calendar_add", "calendar_cancel"]),
        ("Markets & forex", ["market_snapshot", "convert_currency",
                             "set_rate_alert"]),
        ("Smart home", ["home_light", "home_tv", "home_climate", "home_state"]),
        ("Music", ["music_control"]),
        ("Scenes & routines", ["run_scene", "fire_routine"]),
        ("Fleet devices", ["fleet_status", "device_info", "run_remote",
                           "screenshot_device", "analyze_screen", "send_sms",
                           "place_call"]),
    ]
    have = set(_tools.TOOLS)
    lines = ["YOU CAN ACT ON THE REAL WORLD through these tools:"]
    for label, names in groups:
        present = [n for n in names if n in have]
        if present:
            lines.append("- " + label + ": " + ", ".join(present))
    extra = sorted(have - {n for _, names in groups for n in names})
    if extra:
        lines.append("- also: " + ", ".join(extra))
    lines.append("Tool descriptions in the function specs are authoritative; "
                 "prefer acting over explaining.")
    return "\n".join(lines)


class LLMBrain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.llm_cfg = cfg["llm"]
        self.user_name = (cfg.get("user") or {}).get("name", "Boss")
        self.base_url: Optional[str] = None
        self.model: Optional[str] = None
        self._resolve()

    def _resolve(self) -> None:
        llm = self.llm_cfg
        provider = (llm.get("provider") or "auto").lower()
        key = os.environ.get(llm.get("openai_api_key_env", "OPENAI_API_KEY"), "").strip()
        if provider in ("auto", "openai") and key:
            self.base_url = llm.get("openai_base_url",
                                    "https://api.openai.com/v1").rstrip("/")
            self.model = llm.get("openai_model", "gpt-4o-mini")
            return
        # Local Ollama as the auto fallback.
        base = llm.get("ollama_base_url", "http://localhost:11434/v1").rstrip("/")
        try:
            r = requests.get(base + "/models", timeout=2)
            if r.status_code == 200:
                self.base_url = base
                self.model = llm.get("ollama_model", "llama3.2")
        except requests.RequestException:
            pass

    @property
    def available(self) -> bool:
        return self.base_url is not None

    @property
    def label(self) -> str:
        return f"{self.model}" if self.available else "rule brain"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        key = os.environ.get(self.llm_cfg.get("openai_api_key_env",
                                              "OPENAI_API_KEY"), "").strip()
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def chat(self, history: List[dict], memory_block: str = "") -> str:
        now = datetime.now().strftime("%A %d %B %Y, %H:%M")
        block = f"\n{memory_block}\n" if memory_block else ""
        messages = [{"role": "system",
                     "content": SYSTEM_TEMPLATE.format(
                         name=self.user_name, now=now, memory_block=block,
                         manifest=capability_manifest())}]
        messages.extend(history)
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": specs(),
            "temperature": self.llm_cfg.get("temperature", 0.6),
            "max_tokens": self.llm_cfg.get("max_tokens", 300),
        }
        for _ in range(6):  # allow several tool round-trips (agentic chains)
            r = requests.post(self.base_url + "/chat/completions",
                              headers=self._headers(), json=payload, timeout=90)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return (msg.get("content") or "").strip()
            messages.append({"role": "assistant",
                             "content": msg.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute(tc["function"]["name"], cfg=self.cfg, **args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(result)[:2000]})
        return "Still working on it — give me a moment, sir."

    def vision(self, image_b64: str, question: str) -> str:
        """Ask a vision-capable model about a captured screen (PNG)."""
        if not self.available:
            return ""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "You are JARVIS's eyes. Describe the screen "
                            "factually and concisely (2-4 sentences)."},
                {"role": "user", "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"}},
                ]},
            ],
            "temperature": 0.3,
            "max_tokens": 300,
        }
        try:
            r = requests.post(self.base_url + "/chat/completions",
                              headers=self._headers(), json=payload, timeout=60)
            r.raise_for_status()
            return (r.json()["choices"][0]["message"].get("content") or "").strip()
        except requests.RequestException as exc:
            log_vision_failure(exc)
            return ""


def log_vision_failure(exc: Exception) -> None:
    import logging
    logging.getLogger("jarvis.llm").warning("vision call failed: %s", exc)
