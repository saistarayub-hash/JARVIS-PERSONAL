"""Market tools for the LLM brain: snapshot, conversion, rate alerts."""
from __future__ import annotations

from . import tool

_shared: dict = {}


def set_markets(markets) -> None:
    """Called once at startup with the Markets instance."""
    _shared["markets"] = markets


def get_markets():
    return _shared.get("markets")


@tool("market_snapshot",
      "Live forex pairs, crypto and index levels with % change. "
      "Use for 'how are the markets', fx rates, btc price.", {})
def market_snapshot() -> dict:
    m = get_markets()
    if m is None:
        raise RuntimeError("Markets engine isn't wired up.")
    return m.snapshot()


@tool("convert_currency", "Convert an amount between two currencies (e.g. 100 USD ZAR).",
      {"amount": "number", "src": "string: 3-letter currency, e.g. USD",
       "dst": "string: 3-letter currency, e.g. ZAR"})
def convert_currency(amount: float, src: str, dst: str) -> dict:
    m = get_markets()
    if m is None:
        raise RuntimeError("Markets engine isn't wired up.")
    return m.convert(float(amount), src, dst)


@tool("set_rate_alert",
      "Alert the user when a pair/crypto crosses a level, e.g. USDZAR above 19.",
      {"pair": "string: e.g. USDZAR, EURUSD, BTCUSD",
       "op": "string: 'above' or 'below'", "threshold": "number"})
def set_rate_alert(pair: str, op: str, threshold: float) -> dict:
    from .memory_tools import get_memory
    mem = get_memory()
    if mem is None:
        raise RuntimeError("Memory not initialised.")
    op = "below" if op.strip().lower() in ("below", "under", "drops to") else "above"
    aid = mem.add_rate_alert(pair.upper(), op, float(threshold))
    return {"ok": True, "id": aid, "pair": pair.upper(), "op": op,
            "threshold": float(threshold)}
