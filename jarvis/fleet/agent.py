"""JARVIS agent — run on ANY device to connect it to the JARVIS core.

    # your laptop (with activity awareness):
    python -m jarvis.fleet.agent --name my-mac --url ws://192.168.1.10:8595 \\
        --token SECRET --activity

    # a server (health + allowed shell):
    python -m jarvis.fleet.agent --name web-01 --url ws://192.168.1.10:8595 \\
        --token SECRET --allow shell:docker --allow shell:git --allow shell:systemctl

    # an Android phone via Termux:
    python -m jarvis.fleet.agent --name phone --url ws://192.168.1.10:8595 --token SECRET

Security: the token must match the core's `fleet.token`. Shell commands only
run if their prefix is explicitly allowlisted (--allow shell:docker). The
agent only talks outbound to the core — no open ports on the device.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

log = logging.getLogger("jarvis.agent")

DEFAULT_ALLOW = ["telemetry", "activity", "notify", "open_app", "screenshot"]


# ---------------------------------------------------------------- telemetry
def _uptime() -> int:
    try:
        with open("/proc/uptime") as fh:
            return int(float(fh.read().split()[0]))
    except Exception:
        pass
    try:
        out = subprocess.check_output(["sysctl", "-n", "kern.boottime"],
                                      text=True, timeout=3).strip()
        return max(0, int(time.time()) - int(out.split("{")[-1].split(",")[1]))
    except Exception:
        return 0


def telemetry() -> dict:
    info = {"os": f"{platform.system()} {platform.release()}",
            "host": platform.node(), "cpu_count": os.cpu_count(),
            "uptime_s": _uptime()}
    try:
        import psutil
        info["cpu_pct"] = psutil.cpu_percent(interval=None)
        info["ram_pct"] = int(psutil.virtual_memory().percent)
        info["disk_pct"] = int(psutil.disk_usage("/").percent)
        try:
            info["load"] = round(psutil.getloadavg()[0], 2)
        except Exception:
            pass
        try:
            b = psutil.sensors_battery()
            if b:
                info["battery_pct"] = int(b.percent)
        except Exception:
            pass
    except ImportError:
        info["note"] = "pip install psutil for full telemetry"
    return info


def _screenshot() -> dict:
    """Grab the screen as a PNG, base64-encoded (LAN-sized, capped at 4MB)."""
    import base64
    import tempfile
    sysname = platform.system()
    tmp = tempfile.mktemp(suffix=".png")
    try:
        if sysname == "Darwin":
            subprocess.run(["screencapture", "-x", tmp], timeout=10, check=True)
        elif sysname == "Linux":
            ran = False
            for cmd in (["gnome-screenshot", "-f", tmp],
                        ["scrot", "--delay", "0", tmp],
                        ["import", "-window", "root", tmp]):
                if shutil.which(cmd[0]) is None:
                    continue
                try:
                    subprocess.run(cmd, timeout=10, check=True)
                    ran = True
                    break
                except subprocess.CalledProcessError:
                    continue
            if not ran:
                return {"ok": False,
                        "message": ("no screenshot tool found — "
                                    "'sudo apt install scrot' would fix it")}
        elif sysname == "Windows":
            try:
                from PIL import ImageGrab
            except ImportError:
                return {"ok": False,
                        "message": "pip install pillow for Windows screenshots"}
            ImageGrab.grab().save(tmp)
        else:
            return {"ok": False,
                    "message": f"no screenshot support on {sysname}"}
        with open(tmp, "rb") as fh:
            data = fh.read()
        if not data:
            return {"ok": False, "message": "capture came back empty"}
        if len(data) > 4_000_000:
            return {"ok": False, "message": "screenshot too large (>4 MB)"}
        return {"ok": True, "data_b64": base64.b64encode(data).decode()}
    except FileNotFoundError:
        return {"ok": False, "message": "screenshot tool not installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "screenshot timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"screenshot failed: {exc}"}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _notify(text: str) -> dict:
    sysname = platform.system().lower()
    try:
        if sysname == "linux" and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "JARVIS", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sysname == "darwin":
            subprocess.Popen(["osascript", "-e",
                              f'display notification "{text}" with title "JARVIS"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return {"ok": False, "message": "no notifier on this OS"}
        return {"ok": True, "data": {"notified": text}}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# ---------------------------------------------------------------- activity
class ActivityTracker:
    """Polls the foreground window; emits a session event on each switch."""

    def __init__(self, min_seconds: int = 60):
        self.min_seconds = min_seconds
        self.app = ""
        self.title = ""
        self.started = time.time()
        self.totals: dict = {}

    def poll(self) -> dict | None:
        app, title = foreground()
        if app and (app != self.app or title != self.title):
            if self.app:
                secs = int(time.time() - self.started)
                self.totals[self.app] = self.totals.get(self.app, 0) + secs
                self.app, self.title, self.started = app, title, time.time()
                if secs >= self.min_seconds:
                    return {"app": app, "title": title, "seconds": secs,
                            "today": self.totals.get(app, 0) + secs}
            else:
                self.app, self.title, self.started = app, title, time.time()
        return None

    def current(self) -> dict:
        return {"app": self.app, "title": self.title,
                "seconds": int(time.time() - self.started), "today": self.totals}


def foreground() -> tuple:
    """(app, window title) of the active window — best effort per OS."""
    sysname = platform.system().lower()
    try:
        if sysname == "windows":
            return _fg_windows()
        if sysname == "darwin":
            return _fg_mac()
        return _fg_linux()
    except Exception:
        return ("", "")


def _fg_windows():
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title_buf = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, title_buf, 1024)
    app = ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                           False, pid.value)
    if h:
        path = ctypes.create_unicode_buffer(2048)
        n = ctypes.c_uint(2048)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                h, 0, path, ctypes.byref(n)):
            app = os.path.basename(path.value)
        ctypes.windll.kernel32.CloseHandle(h)
    return (app, title_buf.value)


def _fg_mac():
    app = subprocess.check_output(
        ["osascript", "-e",
         'tell application "System Events" to get name of first '
         'application process whose frontmost is true'],
        text=True, timeout=3).strip()
    try:
        title = subprocess.check_output(
            ["osascript", "-e",
             'tell application "System Events" to get name of front window of '
             '(first application process whose frontmost is true)'],
            text=True, timeout=3).strip()
    except Exception:
        title = ""
    return (app, title)


def _fg_linux():
    title = subprocess.check_output(
        ["xdotool", "getactivewindow", "getwindowname"],
        text=True, timeout=3).strip()
    try:
        pid = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowpid"],
            text=True, timeout=3).strip()
        app = open(f"/proc/{pid}/comm").read().strip()
    except Exception:
        app = ""
    return (app, title)


# ---------------------------------------------------------------- commands
def exec_action(action: str, args: dict, allow: list,
                tracker: ActivityTracker | None) -> dict:
    if action == "telemetry":
        return {"ok": True, "data": telemetry()}
    if action == "disk":
        import shutil as _sh
        u = _sh.disk_usage("/")
        return {"ok": True, "data": {"total_gb": u.total // 10**9,
                                     "used_pct": round(u.used / u.total * 100)}}
    if action == "uptime":
        return {"ok": True, "data": {"uptime_s": _uptime()}}
    if action == "processes":
        try:
            import psutil
            top = sorted(psutil.process_iter(["name", "memory_percent"]),
                         key=lambda p: p.info.get("memory_percent") or 0,
                         reverse=True)[:5]
            return {"ok": True, "data": {"top": [
                f"{p.info['name']} (mem {p.info.get('memory_percent') or 0}%)"
                for p in top]}}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
    if action == "activity":
        return {"ok": True,
                "data": tracker.current() if tracker else {"app": ""}}
    if action == "notify":
        if "notify" not in allow:
            return {"ok": False, "message": "not allowed on this agent"}
        return _notify(str(args.get("text", "Jarvis")))
    if action == "open_app":
        if "open_app" not in allow:
            return {"ok": False, "message": "not allowed on this agent"}
        from jarvis.tools import execute
        return execute("open_app", name=args.get("name", ""))
    if action == "screenshot":
        if "screenshot" not in allow:
            return {"ok": False, "message": "not allowed on this agent"}
        return _screenshot()
    if action == "sms":
        if "sms" not in allow:
            return {"ok": False, "message": "not allowed on this device"}
        if not shutil.which("termux-sms-send"):
            return {"ok": False,
                    "message": ("needs Termux:API on this Android device "
                                "(pkg install termux-api)")}
        to, text = str(args.get("to", "")), str(args.get("text", ""))
        if not to or not text:
            return {"ok": False, "message": "sms needs 'to' and 'text'"}
        try:
            subprocess.run(["termux-sms-send", "-n", to, text],
                           timeout=20, check=True)
            return {"ok": True, "data": {"sent_to": to}}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"sms failed: {exc}"}
    if action == "call":
        if "call" not in allow:
            return {"ok": False, "message": "not allowed on this device"}
        num = str(args.get("number", ""))
        if not num:
            return {"ok": False, "message": "call needs 'number'"}
        if shutil.which("termux-telephony-call"):
            try:
                subprocess.run(["termux-telephony-call", num],
                               timeout=20, check=True)
                return {"ok": True, "data": {"calling": num}}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"call failed: {exc}"}
        try:  # desktop fallback: tel: URI
            import webbrowser
            webbrowser.open(f"tel:{num}")
            return {"ok": True, "data": {"calling": num}}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"call failed: {exc}"}
    if action == "shell":
        prefixes = [p[len("shell:"):] for p in allow if p.startswith("shell:")]
        cmd = (args.get("cmd") or "").strip()
        if not cmd or not prefixes or \
                not any(cmd.startswith(p) for p in prefixes):
            return {"ok": False,
                    "message": "shell command not in this agent's allowlist"}
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=60)
            return {"ok": r.returncode == 0,
                    "message": ("" if r.returncode == 0
                                else f"exited {r.returncode}"),
                    "data": {"code": r.returncode,
                             "stdout": r.stdout[-2000:],
                             "stderr": r.stderr[-500:]}}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "command timed out (60s)"}
    return {"ok": False, "message": f"unknown action '{action}'"}


# ---------------------------------------------------------------- main loop
async def run(args) -> None:
    import websockets
    url = (f"{args.url.rstrip('/')}/fleet/ws"
           f"?name={quote(args.name)}&token={quote(args.token)}")
    allow = list(DEFAULT_ALLOW) + list(args.allow or [])
    tracker = ActivityTracker() if args.activity else None
    backoff = 2
    log.info("agent '%s' starting -> %s (allow: %s)", args.name, args.url, allow)
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                backoff = 2
                await ws.send(json.dumps({
                    "type": "auth", "os": platform.system(),
                    "meta": {"python": sys.version.split()[0],
                             "allow": allow}}))
                log.info("connected as '%s'", args.name)
                hb_task = asyncio.create_task(_heartbeat(ws, args.interval))
                act_task = (asyncio.create_task(_activity_loop(ws, tracker))
                            if tracker else None)
                try:
                    async for raw in ws:
                        try:
                            m = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if m.get("type") == "cmd":
                            res = await asyncio.to_thread(
                                exec_action, m.get("action"),
                                m.get("args") or {}, allow, tracker)
                            await ws.send(json.dumps(
                                {"type": "result", "id": m.get("id"), **res}))
                finally:
                    hb_task.cancel()
                    if act_task:
                        act_task.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("connection lost (%s) — retrying in %ss", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def _heartbeat(ws, interval: int) -> None:
    await asyncio.sleep(1)  # let first CPU sample warm up
    while True:
        await ws.send(json.dumps(
            {"type": "heartbeat", "telemetry": telemetry()}))
        await asyncio.sleep(interval)


async def _activity_loop(ws, tracker: ActivityTracker) -> None:
    while True:
        await asyncio.sleep(4)
        session = await asyncio.to_thread(tracker.poll)
        if session:
            await ws.send(json.dumps(
                {"type": "event", "kind": "activity", "data": session}))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="JARVIS device agent")
    ap.add_argument("--name", required=True, help="device name, e.g. web-01")
    ap.add_argument("--url", required=True,
                    help="core URL, e.g. ws://192.168.1.10:8595")
    ap.add_argument("--token", required=True, help="shared fleet token")
    ap.add_argument("--activity", action="store_true",
                    help="track the foreground app (laptops/desktops)")
    ap.add_argument("--interval", type=int, default=30,
                    help="heartbeat seconds (default 30)")
    ap.add_argument("--allow", action="append", default=[],
                    help="extra allowed actions, e.g. --allow shell:docker")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("agent stopped")


if __name__ == "__main__":
    main()
