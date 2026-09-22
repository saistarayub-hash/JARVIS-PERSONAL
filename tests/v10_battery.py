"""v10 battery: integration is real — shell command end-to-end, installers
write real artifacts to a real (temporary) HOME, uninstall cleans up, and the
/api/command path lights up the browser UI too."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
API = "http://127.0.0.1:8595"
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'} {name} {str(extra)[:190]}")


def api(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method or
                                 ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def sh(cmd, env=None):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=60, env=env)
    return p


def main():
    # 1) HTTP entry point
    r = api("/api/command", {"text": "what time is it"})
    check("/api/command answers", r.get("ok") and ":" in r.get("reply", ""),
          r.get("reply", "")[:120])

    # 2) a command typed from the shell appears in the browser UI (broadcast)
    import asyncio
    import websockets

    async def ws_probe():
        async with websockets.connect("ws://127.0.0.1:8595/ws") as ws:
            await ws.recv()  # hello
            got = {"user": None, "reply": None}

            async def post():
                await asyncio.sleep(0.4)
                api("/api/command", {"text": "hello jarvis"})
            sender = asyncio.create_task(post())
            end = time.time() + 12
            while time.time() < end and not (got["user"] and got["reply"]):
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except Exception:
                    continue
                if m.get("type") == "user":
                    got["user"] = m.get("text")
                elif m.get("type") == "reply":
                    got["reply"] = m.get("reply")
            await sender
            return got
    g = asyncio.run(ws_probe())
    check("api command mirrors into live UI",
          g["user"] == "hello jarvis" and bool(g["reply"]),
          g)

    # 3) CLI module straight from the repo
    p = sh('python3 -m jarvis.cli "brief me"')
    check("python3 -m jarvis.cli works",
          p.returncode == 0 and "brief" in p.stdout.lower(), p.stdout[:130])

    # 4) install into a throwaway HOME — real files, real idempotency
    home = tempfile.mkdtemp(prefix="fakehome-")
    Path(home, ".bashrc").write_text("# user rc\n")
    env = dict(os.environ, HOME=home)
    p = sh(f'python3 -m jarvis.cli install', env=env)
    out = p.stdout
    check("install ran", p.returncode == 0 and "file:" in out, out[:200])
    shim = Path(home, ".local/bin/jarvis")
    unit = Path(home, ".config/systemd/user/jarvis.service")
    check("shim + systemd unit written for real",
          shim.exists() and unit.exists() and os.access(shim, os.X_OK),
          [str(shim), str(unit)])
    check("unit points at this repo headless",
          unit.exists() and "run.py" in unit.read_text()
          and "--headless" in unit.read_text(), unit.read_text()[:150]
          if unit.exists() else "")
    check("service outcome reported honestly",
          "failed" in out.lower() or "run: systemctl" in out, out[-200:])

    p2 = sh(f'python3 -m jarvis.cli install', env=env)
    rc = Path(home, ".bashrc").read_text()
    check("second install idempotent", rc.count(">>> jarvis integration >>>") == 1,
          rc[:120])

    # THE moment: use the freshly installed command like a normal user would
    p3 = sh(f'"{shim}" what is the date', env=env)
    check("installed `jarvis` command talks to the core",
          p3.returncode == 0 and any(y in p3.stdout for y in
                                     ("2026", "September", "Sept")),
          p3.stdout.strip()[:120])

    # 5) uninstall leaves the home exactly as found (bar empty .local/bin dir)
    p4 = sh(f'python3 -m jarvis.cli uninstall', env=env)
    check("uninstall removes its files",
          not shim.exists() and not unit.exists()
          and ">>> jarvis integration >>>" not in Path(home, ".bashrc").read_text()
          and "# user rc" in Path(home, ".bashrc").read_text(), p4.stdout[:150])

    # 6) dry run writes nothing
    home2 = tempfile.mkdtemp(prefix="fakehome2-")
    env2 = dict(os.environ, HOME=home2)
    p5 = sh('python3 -m jarvis.cli install --dry', env=env2)
    wrote = any(Path(home2).rglob("jarvis*"))
    check("dry run: plan printed, nothing written",
          not wrote and "dry run" in p5.stdout, p5.stdout[:160])

    # 7) status subcommand is truthful about an uninstalled machine
    p6 = sh('python3 -m jarvis.cli status', env=dict(os.environ, HOME=home))
    check("status says absent + core online",
          "absent" in p6.stdout and "online" in p6.stdout, p6.stdout[:200])

    print(f"=== {sum(1 for _, ok in results if ok)}/{len(results)} passed ===")
    return all(ok for _, ok in results)


raise SystemExit(0 if main() else 1)
