"""JARVIS from any terminal — the integration entry point (v10).

    jarvis "brief me"                # talk to the running core
    jarvis status                    # core health + what's installed where
    jarvis install [--dry]           # autostart + shell command + (real) service
    jarvis uninstall

Runs both as `python3 -m jarvis.cli ...` and through the installed
~/.local/bin/jarvis shim. Talks to POST /api/command on the core.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any, Dict, Optional


def _api_base(port: int) -> str:
    host = os.environ.get("JARVIS_HOST", "127.0.0.1")
    return f"http://{host}:{port}"


def command(text: str, port: int, timeout: float = 120.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        _api_base(port) + "/api/command",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path: str, port: int, timeout: float = 8.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(_api_base(port) + path,
                                    timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 — offline is a normal answer here
        return None


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis",
                                 description="talk to JARVIS from any shell")
    ap.add_argument("words", nargs="*",
                    help='what to say, or: status | install | uninstall')
    ap.add_argument("--port", type=int, default=int(
        os.environ.get("JARVIS_PORT", "8595")))
    ap.add_argument("--json", action="store_true", help="raw JSON reply")
    ap.add_argument("--dry", action="store_true",
                    help="with install: show the plan, write nothing")
    args = ap.parse_args(argv)

    text = " ".join(args.words).strip()
    if not text:
        ap.print_help()
        return 0

    if text in ("install", "uninstall", "status"):
        if text == "status":
            core = _get("/api/state", args.port)
            from .integrate import Integrator, report_text
            integ = Integrator(port=args.port).status()
            if args.json:
                print(json.dumps({"core": core, "integration": integ}, indent=2))
            else:
                if core:
                    print(f"core: online — brain '{core.get('brain_label')}', "
                          f"state {core.get('state')}, llm={core.get('llm')}, "
                          f"voice={core.get('voice')}")
                else:
                    print("core: OFFLINE on port "
                          f"{args.port} (is run.py going?)")
                print(report_text({"os": integ["os"], "root": integ["root"],
                                   "files": list(integ["files"]),
                                   "rc": [f"service: {integ['service']}"]}))
                for path, st in integ["files"].items():
                    print(f"  {st:>9}  {path}")
            return 0 if core else 1
        from .integrate import Integrator, report_text
        ini = Integrator(port=args.port)
        rep = ini.install(dry=args.dry) if text == "install" else ini.uninstall()
        print(report_text(rep))
        return 0

    try:
        res = command(text, args.port)
    except Exception as exc:  # noqa: BLE001
        print(f"jarvis: can't reach the core on port {args.port} "
              f"({exc.__class__.__name__}) — start it with `python3 run.py` "
              "or install autostart: `jarvis install`", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(res.get("reply", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
