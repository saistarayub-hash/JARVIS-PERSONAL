#!/usr/bin/env python3
"""Point JARVIS at a real LLM brain (Token Harbor's free deepseek route).

    python scripts/set_llm_key.py thk_live_xxx     # enable
    python scripts/set_llm_key.py --off            # back to rule brain

Writes only to config.yaml (gitignored). Env var OPENAI_API_KEY still wins
at runtime if you prefer that.
"""
import sys
from pathlib import Path

import yaml

BASE = "https://tokenharbor.ai/v1"
MODEL = "deepseek-v4.1-flash:free"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        print("config.yaml not found — run from the JARVIS folder")
        return 1
    text = cfg_path.read_text()
    data = yaml.safe_load(text) or {}
    root = data.get("jarvis") if isinstance(data.get("jarvis"), dict) else data
    llm = root.setdefault("llm", {})
    if sys.argv[1] == "--off":
        llm["provider"] = "none"
        llm.pop("openai_api_key", None)
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False))
        print("llm off — rule brain from here on")
        return 0
    key = sys.argv[1].strip()
    if len(key) < 12:
        print("that doesn't look like a key (too short)")
        return 1
    llm.update({
        "provider": "openai",
        "openai_base_url": BASE,
        "openai_model": MODEL,
        "openai_api_key_env": "OPENAI_API_KEY",
        "openai_api_key": key,
        "temperature": 0.6,
        "max_tokens": 400,
    })
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"llm brain ready: {MODEL} via tokenharbor (config.yaml stays local)")
    # live ping, honest about what happens
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            BASE + "/chat/completions",
            data=json.dumps({"model": MODEL,
                             "messages": [{"role": "user", "content": "ping"}],
                             "max_tokens": 8}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode())
        if body.get("choices"):
            print("ping: the brain answers — you're live.")
        else:
            print(f"ping: endpoint replied oddly: {str(body)[:160]}")
    except Exception as exc:  # noqa: BLE001
        print(f"ping failed from here: {exc.__class__.__name__} — key saved; "
              "if you're offline or the provider is busy, JARVIS still runs "
              "the rule brain meanwhile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
