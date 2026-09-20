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
- You command a fleet of devices (laptops, servers, phones). Use fleet_status to see what's online, device_info for details, run_remote for allowed actions on a device. Never invent device data — query it.
- The user has named prep routines (fire_routine). Offer them when the time fits.
- Current local time: {now}.
{memory_block}"""


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
                         name=self.user_name, now=now, memory_block=block)}]
        messages.extend(history)
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": specs(),
            "temperature": self.llm_cfg.get("temperature", 0.6),
            "max_tokens": self.llm_cfg.get("max_tokens", 300),
        }
        for _ in range(4):  # allow a few tool round-trips
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
