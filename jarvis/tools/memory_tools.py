"""Memory tools exposed to the LLM brain (function calling)."""
from __future__ import annotations

from . import tool

_shared: dict = {}


def set_memory(mem) -> None:
    """Called once at startup with the Memory instance."""
    _shared["memory"] = mem


def get_memory():
    return _shared.get("memory")


@tool("remember_fact", "Store a lasting fact about the user in long-term memory.",
      {"text": "string: the fact, e.g. 'user prefers metric units'"})
def remember_fact(text: str) -> dict:
    mem = _shared.get("memory")
    if mem is None:
        raise RuntimeError("Memory not initialised.")
    return {"stored": mem.remember(text), "text": text}


@tool("recall_facts", "Search long-term memory for facts relevant to a query.",
      {"query": "string: what to look for"})
def recall_facts(query: str, k: int = 3) -> dict:
    mem = _shared.get("memory")
    return {"facts": mem.recall(query, k) if mem else []}
