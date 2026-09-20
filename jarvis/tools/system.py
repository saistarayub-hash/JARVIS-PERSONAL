"""System-level tools: time, date, laptop health, volume, math, jokes."""
from __future__ import annotations

import ast
import datetime
import operator
import os
import platform
import random
import shutil
import subprocess

from . import tool

JOKES = [
    "I would tell you a UDP joke, but you might not get it.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "There are 10 kinds of people: those who understand binary, and those who don't.",
    "I read your last commit message. It said 'misc'. I'm still processing that.",
    "Why did the developer go broke? He used up all his cache.",
    "A SQL query walks into a bar, approaches two tables and asks: 'Can I join you?'",
    "It's not a bug, it's an untested feature. I'd like that on the invoice.",
]

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


@tool("get_time", "Get the current local time.")
def get_time() -> dict:
    now = datetime.datetime.now()
    return {"time": now.strftime("%H:%M"),
            "full": now.strftime("%A %d %B %Y, %H:%M")}


@tool("get_date", "Get today's date.")
def get_date() -> dict:
    return {"date": datetime.datetime.now().strftime("%A, %d %B %Y")}


@tool("system_stats", "Check laptop health: CPU load, RAM usage, battery.")
def system_stats() -> dict:
    info = {"platform": f"{platform.system()} {platform.release()}",
            "cpu_count": os.cpu_count() or "?"}
    try:
        import psutil
        info["cpu_load_1m"] = round(psutil.getloadavg()[0], 2)
        info["ram_used_pct"] = int(psutil.virtual_memory().percent)
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                info["battery_pct"] = int(batt.percent)
        except Exception:
            pass
    except ImportError:
        info["note"] = "(install psutil for full stats: pip install psutil)"
    return info


@tool("set_volume", "Adjust the system volume.",
      {"action": "string (optional): up | down | mute | set",
       "level": "integer (optional): 0-100, only for action=set"})
def set_volume(action: str = "up", level: int | None = None) -> dict:
    sysname = platform.system().lower()
    if sysname == "linux" and shutil.which("pactl"):
        arg = {"up": "+10%", "down": "-10%", "mute": "mute"}.get(action, f"{int(level or 50)}%")
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", arg], check=False)
        return {"detail": f"Volume {action}."}
    if sysname == "darwin":
        if action == "set":
            expr = str(max(0, min(100, int(level or 50))))
        else:
            expr = {"up": "((output volume)+10", "down": "((output volume)-10",
                    "mute": "0"}.get(action, "((output voice)+10")
        subprocess.run(["osascript", "-e", f"set volume output volume {expr}"], check=False)
        return {"detail": f"Volume {action}."}
    if sysname == "windows":
        try:
            import pythoncom
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            pythoncom.CoInitialize()
            vol = AudioUtilities.GetSpeakers().Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            if action == "set":
                vol.SetMasterVolumeLevelScalar(max(0, min(100, int(level or 50))) / 100.0, None)
            elif action == "mute":
                vol.SetMute(1, None)
            elif action == "down":
                vol.ChangeMasterVolumeLevelScalar(-0.1, None)
            else:
                vol.ChangeMasterVolumeLevelScalar(0.1, None)
            return {"detail": f"Volume {action}."}
        except ImportError:
            raise RuntimeError("For volume control on Windows: pip install pycaw comtypes")
    raise RuntimeError("I couldn't find a volume control for this OS.")


@tool("math", "Evaluate a math expression safely.",
      {"expression": "string: e.g. '12*(7+4)/2'"})
def math(expression: str) -> dict:
    value = _safe_eval(ast.parse(expression, mode="eval"))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return {"value": value}


@tool("joke", "Tell a short developer joke.")
def joke() -> dict:
    return {"joke": random.choice(JOKES)}
