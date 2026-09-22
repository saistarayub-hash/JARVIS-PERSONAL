"""Markets engine: forex, crypto, indices — with graceful provider fallbacks.

Provider chain (first healthy one wins):
  fx pairs   : stooq.com CSV quotes (intraday) -> frankfurter.app (ECB daily)
               -> open.er-api.com (daily)
  crypto     : coingecko.com simple price
  indices    : stooq.com (^spx, ^ndx, xauusd ...)

If nothing is reachable (air-gapped box, sandbox, plane wifi) and JARVIS runs
with --demo, a clearly labelled simulated feed keeps the UX exercisable.
On a real machine you always get real numbers or an honest error.
"""
from __future__ import annotations

import logging
import math
import random
import time
from typing import Dict, Optional

log = logging.getLogger("jarvis.fx")

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDZAR"]
DEFAULT_CRYPTO = ["bitcoin", "ethereum"]
DEFAULT_INDICES = {"^spx": "S&P 500", "^ndx": "Nasdaq 100", "xauusd": "Gold"}

CRYPTO_SYMBOL = {"bitcoin": "BTC", "ethereum": "ETH"}

# Sim anchors: realistic mid-2020s levels for the offline demo feed.
_ANCHORS = {
    "EURUSD": 1.085, "GBPUSD": 1.271, "USDJPY": 150.4, "USDZAR": 18.62,
    "AUDUSD": 0.662, "USDCAD": 1.362, "USDCHF": 0.884,
    "BTCUSD": 64200.0, "ETHUSD": 3120.0,
    "^spx": 5610.0, "^ndx": 19850.0, "xauusd": 2385.0,
}
# units of currency per 1 USD, for cross conversion
_USD_RATE = {
    "USD": 1.0, "EUR": 1 / 1.085, "GBP": 1 / 1.271, "JPY": 150.4,
    "ZAR": 18.62, "AUD": 1 / 0.662, "CAD": 1.362, "CHF": 0.884,
}


def _norm_pair(text: str) -> Optional[str]:
    """'eur/usd', 'EURUSD', 'the rand', 'cable' -> 'EURUSD' / 'USDZAR' ..."""
    t = (text or "").strip().lower().replace("/", "").replace(" ", "")
    aliases = {"rand": "USDZAR", "zar": "USDZAR", "euro": "EURUSD",
               "cable": "GBPUSD", "pound": "GBPUSD", "yen": "USDJPY",
               "btc": "BTCUSD", "bitcoin": "BTCUSD", "eth": "ETHUSD",
               "ether": "ETHUSD", "ethereum": "ETHUSD", "gold": "XAUUSD"}
    if t in aliases:
        return aliases[t]
    if len(t) == 6 and t.isalnum():
        return t.upper()
    return None


class Markets:
    def __init__(self, cfg: dict, demo: bool = False):
        mcfg = (cfg or {}).get("markets", {}) or {}
        self.pairs = [p.upper() for p in mcfg.get("pairs", DEFAULT_PAIRS)]
        self.crypto = list(mcfg.get("crypto", DEFAULT_CRYPTO))
        self.indices = dict(mcfg.get("indices", DEFAULT_INDICES))
        self.ttl = int(mcfg.get("poll_minutes", 5)) * 60
        self.demo = demo
        self._cache: Optional[dict] = None
        self._cache_ts = 0.0

    # ---------------- public ----------------
    def snapshot(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < self.ttl:
            return self._cache
        snap = self._fetch_real()
        if snap is None:
            if self.demo:
                snap = self._sim_snapshot()
            else:
                snap = {"ok": False, "simulated": False,
                        "message": ("No market-data provider is reachable from "
                                    "this machine (tried stooq, frankfurter, "
                                    "er-api, coingecko).")}
        if snap.get("ok"):
            self._cache, self._cache_ts = snap, time.time()
        return snap

    def price(self, symbol: str) -> Optional[float]:
        snap = self.snapshot()
        if not snap.get("ok"):
            return None
        for bucket in ("pairs", "crypto", "indices"):
            row = (snap.get(bucket) or {}).get(symbol)
            if row:
                return row["price"]
        return None

    def convert(self, amount: float, src: str, dst: str) -> Optional[dict]:
        src, dst = src.upper(), dst.upper()
        snap = self.snapshot()
        rates = dict((snap.get("rates_usd") or {}) if snap.get("ok") else {})
        if self.demo and not rates:
            rates = dict(_USD_RATE)
        if src not in rates or dst not in rates:
            known = ", ".join(sorted(rates or _USD_RATE))
            return {"ok": False,
                    "message": f"I don't have a rate for {src}/{dst}. "
                               f"Currencies I know: {known}."}
        per_usd_src, per_usd_dst = rates[src], rates[dst]
        out = amount * per_usd_dst / per_usd_src
        return {"ok": True, "amount": amount, "src": src, "dst": dst,
                "value": out, "rate": per_usd_dst / per_usd_src,
                "simulated": bool(snap.get("simulated"))}

    # ---------------- providers ----------------
    def _fetch_real(self) -> Optional[dict]:
        import requests
        out = {"ok": True, "simulated": False, "ts": time.time(),
               "pairs": {}, "crypto": {}, "indices": {},
               "rates_usd": {"USD": 1.0},
               "source": ""}
        syms = ",".join([p.lower() for p in self.pairs] + list(self.indices))
        try:
            r = requests.get(f"https://stooq.com/q/l/?s={syms}"
                             f"&f=sd2t2ohlcv&h&e=csv", timeout=6,
                             headers={"User-Agent": "JARVIS/1.0"})
            r.raise_for_status()
            for line in r.text.strip().splitlines()[1:]:
                f = line.split(",")
                if len(f) < 7:
                    continue
                sym, close, opn = f[0].upper(), f[6], f[3]
                try:
                    close, opn = float(close), float(opn)
                except ValueError:
                    continue
                label = self.indices.get(f[0].lower(), sym)
                row = {"price": close,
                       "chg_pct": round((close - opn) / opn * 100, 2) if opn else 0.0}
                if sym in self.pairs:
                    out["pairs"][sym] = row
                    out["rates_usd"].update(_pair_usd_rate(sym, close))
                elif f[0].lower() in self.indices:
                    out["indices"][label] = row
            if out["pairs"]:
                out["source"] = "stooq"
        except Exception as exc:  # noqa: BLE001
            log.debug("stooq failed: %s", exc)
        if not out["pairs"]:
            self._daily_fallback(out)
        try:
            ids = ",".join(self.crypto)
            r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": ids, "vs_currencies": "usd",
                                     "include_24hr_change": "true"}, timeout=6)
            r.raise_for_status()
            data = r.json()
            for cid in self.crypto:
                row = data.get(cid)
                if row:
                    sym = CRYPTO_SYMBOL.get(cid, cid[:4].upper()) + "USD"
                    out["crypto"][sym] = {
                        "price": row["usd"],
                        "chg_pct": round(row.get("usd_24h_change") or 0.0, 2)}
            if out["crypto"]:
                out["source"] += "+coingecko"
        except Exception as exc:  # noqa: BLE001
            log.debug("coingecko failed: %s", exc)
        if not out["pairs"] and not out["crypto"] and not out["indices"]:
            return None
        return out

    def _daily_fallback(self, out: dict) -> None:
        """ECB (frankfurter) then open.er-api.com — daily rates, no intraday."""
        import requests
        try:
            r = requests.get("https://api.frankfurter.app/latest", timeout=6)
            r.raise_for_status()
            rates = r.json().get("rates", {})  # base EUR
            if rates and "USD" in rates:
                usd_per_eur = rates["USD"]
                out["rates_usd"] = {
                    cur: amt / usd_per_eur for cur, amt in rates.items()}
                out["rates_usd"]["EUR"] = 1 / usd_per_eur
                for p in self.pairs:
                    v = _cross(p, out["rates_usd"])
                    if v:
                        out["pairs"][p] = {"price": v, "chg_pct": 0.0}
                out["source"] = "frankfurter(ECB daily)"
                return
        except Exception as exc:  # noqa: BLE001
            log.debug("frankfurter failed: %s", exc)
        try:
            r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=6)
            r.raise_for_status()
            rates = r.json().get("rates", {})
            if rates:
                out["rates_usd"] = dict(rates)
                out["rates_usd"]["USD"] = 1.0
                for p in self.pairs:
                    v = _cross(p, out["rates_usd"])
                    if v:
                        out["pairs"][p] = {"price": v, "chg_pct": 0.0}
                out["source"] = "open.er-api(daily)"
        except Exception as exc:  # noqa: BLE001
            log.debug("er-api failed: %s", exc)

    # ---------------- offline demo feed ----------------
    def _sim_snapshot(self) -> dict:
        now = time.time()
        rnd = random.Random(int(now // 30))  # drifts every 30s, stable between
        pairs, crypto, indices = {}, {}, {}
        for sym in self.pairs:
            anchor = _ANCHORS.get(sym, 1.0)
            wobble = math.sin(now / 900 + hash(sym) % 7) * 0.004
            px = anchor * (1 + wobble + rnd.uniform(-0.0012, 0.0012))
            dec = 2 if px > 50 else 4
            pairs[sym] = {"price": round(px, dec),
                          "chg_pct": round(wobble * 100, 2)}
        for cid in self.crypto:
            sym = CRYPTO_SYMBOL.get(cid, cid[:4].upper()) + "USD"
            anchor = _ANCHORS.get(sym, 100.0)
            wobble = math.sin(now / 700 + len(cid)) * 0.012
            crypto[sym] = {"price": round(anchor * (1 + wobble), 0),
                           "chg_pct": round(wobble * 100, 2)}
        for slug, label in self.indices.items():
            anchor = _ANCHORS.get(slug, 1000.0)
            wobble = math.sin(now / 1100 + len(label)) * 0.005
            indices[label] = {"price": round(anchor * (1 + wobble), 1),
                              "chg_pct": round(wobble * 100, 2)}
        return {"ok": True, "simulated": True, "ts": now,
                "pairs": pairs, "crypto": crypto, "indices": indices,
                "rates_usd": dict(_USD_RATE),
                "source": "offline demo feed (simulated)"}


def _pair_usd_rate(pair: str, price: float) -> Dict[str, float]:
    """Derive units-per-USD entries from a quoted pair price."""
    if not price:
        return {}
    base, quote = pair[:3], pair[3:]
    if base == "USD":
        return {quote: price}
    if quote == "USD":
        return {base: 1 / price}
    return {}


def _cross(pair: str, rates_usd: Dict[str, float]) -> Optional[float]:
    base, quote = pair[:3], pair[3:]
    b, q = rates_usd.get(base), rates_usd.get(quote)
    if not b or not q:
        return None
    return round(q / b, 5)  # quote units per base unit
