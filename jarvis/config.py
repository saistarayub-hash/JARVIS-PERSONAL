"""Configuration loading with sane defaults.

Everything lives in config.yaml (copy config.example.yaml to get started).
Missing keys fall back to DEFAULTS, so a partial file is fine.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "name": "JARVIS",
    "user": {"name": "Boss", "default_city": "London"},
    "voice": {
        "enabled": False,
        "wake_word": "hey jarvis",
        "stt": "faster-whisper",
        "stt_model": "base.en",        # tiny.en | base.en | small.en
        "tts": "piper",                 # piper | espeak | pyttsx3
        "piper_voice": "en_GB-alan-medium",
        "piper_model_dir": "data/voices",
        "listen_seconds_max": 12,
    },
    "llm": {
        "provider": "auto",            # auto | openai | ollama | none
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "gpt-4o-mini",
        "openai_api_key_env": "OPENAI_API_KEY",
        "ollama_base_url": "http://localhost:11434/v1",
        "ollama_model": "llama3.2",
        "temperature": 0.6,
        "max_tokens": 300,
    },
    "memory": {"db": "data/memory.db"},
    "learner": {"proactive": True, "min_uses": 2, "window_hours": 1},
    "web": {"host": "127.0.0.1", "port": 8595},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    user_cfg: Dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
    # A config.yaml may wrap everything in a top-level `jarvis:` key.
    if "jarvis" in user_cfg and isinstance(user_cfg["jarvis"], dict):
        user_cfg = user_cfg["jarvis"]
    return _deep_merge(DEFAULTS, user_cfg)
