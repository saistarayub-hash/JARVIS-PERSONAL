"""Tool registry — everything JARVIS can actually *do* on the laptop.

Tools are plain functions tagged with @tool. The rule brain, the LLM brain
(function calling) and the HTTP API all dispatch through execute().
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

TOOLS: Dict[str, Dict[str, Any]] = {}


def tool(name: str, description: str,
         parameters: Optional[Dict[str, str]] = None):
    def deco(fn: Callable):
        TOOLS[name] = {"name": name, "description": description,
                       "parameters": dict(parameters or {}), "fn": fn}
        return fn
    return deco


def execute(tool_name: str, cfg: Optional[dict] = None, **kwargs) -> Dict[str, Any]:
    """Run a tool by name. Errors are returned as data, never raised."""
    entry = TOOLS.get(tool_name)
    if entry is None:
        return {"ok": False, "message": f"Unknown tool '{tool_name}'."}
    if cfg is not None and "default_city" in entry["parameters"]:
        kwargs.setdefault("default_city", (cfg.get("user") or {}).get("default_city"))
    try:
        return {"ok": True, "tool": tool_name, "result": entry["fn"](**kwargs)}
    except TypeError as exc:
        return {"ok": False, "tool": tool_name, "message": f"Bad arguments for {tool_name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 — a tool error is data, not a crash
        return {"ok": False, "tool": tool_name, "message": str(exc)}


def specs() -> list:
    """Tool specs for LLM function calling."""
    out = []
    for name, e in TOOLS.items():
        props = {k: {"type": v} for k, v in e["parameters"].items()}
        required = [k for k, v in e["parameters"].items() if "optional" not in v.lower()]
        out.append({"type": "function", "function": {
            "name": name,
            "description": e["description"],
            "parameters": {"type": "object", "properties": props,
                           "required": required},
        }})
    return out


from . import system, apps, web, files, memory_tools, calendar_tools  # noqa: E402,F401
