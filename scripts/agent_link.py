#!/usr/bin/env python3
"""Compute the phone-pairing command from this machine's live config."""
import platform
import re
import subprocess
import sys
from pathlib import Path


def local_ip() -> str:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["ipconfig", "getifaddr", "en0"],
                                 capture_output=True, text=True).stdout
        else:
            out = subprocess.run(["hostname", "-I"], capture_output=True,
                                 text=True).stdout.split()
            return (out[0] if out else "") or _route_ip()
        out = out.strip()
        return out or _route_ip()
    except Exception:  # noqa: BLE001 — fall through to the route trick
        return _route_ip()


def _route_ip() -> str:
    try:
        out = subprocess.run(["ip", "route", "get", "8.8.8.8"],
                             capture_output=True, text=True).stdout
        m = re.search(r"src (\S+)", out)
        return m.group(1) if m else "<laptop-ip>"
    except Exception:  # noqa: BLE001
        return "<laptop-ip>"


def main() -> int:
    port, token = "8595", ""
    cfg = Path("config.yaml")
    if cfg.exists():
        text = cfg.read_text()
        try:
            import yaml
            data = yaml.safe_load(text) or {}
            j = data.get("jarvis", data)
            port = str((j.get("web") or {}).get("port", port))
            token = str((j.get("fleet") or {}).get("token", "") or "")
        except Exception:  # noqa: BLE001 — no yaml? regex it
            m = re.search(r"web:[\s\S]*?port:\s*(\d+)", text)
            if m:
                port = m.group(1)
            m = re.search(r"token:\s*(\S+)", text)
            if m:
                token = m.group(1)
    if not token or token.startswith("change-me"):
        token = "<fleet token>"
    ip = local_ip()
    print("On the phone (Termux), paste:\n")
    print("  curl -fsSL https://raw.githubusercontent.com/saistarayub-hash/"
          "JARVIS-PERSONAL/main/scripts/termux-bootstrap.sh "
          f"| bash -s -- ws://{ip}:{port} {token}\n")
    if ip == "<laptop-ip>":
        print("(couldn't detect a LAN IP — replace <laptop-ip> manually)")
    if token == "<fleet token>":
        print("(config.yaml fleet.token is the example value — set a real "
              "token on the core first, or the agent will be refused)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
