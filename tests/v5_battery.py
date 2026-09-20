"""v5 battery: web read, news, forex/crypto/markets, rate alerts, world clock."""
import asyncio, json, time, urllib.request

import websockets

BASE = "ws://127.0.0.1:8595/ws"
results, side = [], []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'} {name} {str(extra)[:190]}")


async def send_and_wait(ws, text, timeout_s=14):
    await ws.send(json.dumps({"type": "chat", "text": text}))
    reply = None
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 2))
        except Exception:
            if reply is not None:
                break
            continue
        if m["type"] == "reply":
            reply = m
        elif m["type"] != "state":
            side.append(m)
    return reply


async def main():
    async with websockets.connect(BASE) as ws:
        hello = json.loads(await ws.recv())
        mk = hello.get("markets") or {}
        check("hello markets (sim labelled)", mk.get("simulated") is True
              and "EURUSD" in (mk.get("pairs") or {}), json.dumps(mk)[:140])

        r = await send_and_wait(ws, "markets")
        check("markets snapshot reply", r and "Market snapshot" in r["reply"]
              and "EURUSD" in r["reply"], r and r["reply"][:160])

        r = await send_and_wait(ws, "how much is 100 usd in zar")
        check("fx conversion", r and "ZAR" in r["reply"] and "1,8" in r["reply"],
              r and r["reply"])

        r = await send_and_wait(ws, "eurusd")
        check("pair rate", r and "EURUSD is at" in r["reply"], r and r["reply"])

        r = await send_and_wait(ws, "bitcoin price")
        check("crypto price", r and "BTCUSD is at" in r["reply"], r and r["reply"])

        r = await send_and_wait(ws, "what's the news")
        check("news (demo feed labelled)", r and "Headlines" in r["reply"]
              and "demo feed" in r["reply"], r and r["reply"][:160])

        r = await send_and_wait(ws, "time in tokyo")
        check("world clock", r and "Tokyo" in r["reply"] and "ahead" in r["reply"],
              r and r["reply"])

        r = await send_and_wait(ws, "https://example.com")
        check("read url graceful offline", r and ("couldn't reach" in r["reply"]
              or "example.com" in r["reply"]), r and r["reply"][:120])

        r = await send_and_wait(ws, "watch usdzar above 1")
        check("rate alert armed", r and "Watching USDZAR" in r["reply"],
              r and r["reply"])

        alert = None
        deadline = time.time() + 150
        while time.time() < deadline and alert is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] == "alert" and "USDZAR" in m.get("text", ""):
                alert = m
            else:
                side.append(m)
        check("rate alert fired", alert is not None, json.dumps(alert or {})[:160])

        r = await send_and_wait(ws, "rate alerts")
        check("alerts list empty after hit", r and "No rate alerts armed" in r["reply"],
              r and r["reply"])

        r = await send_and_wait(ws, "brief me")
        check("brief has markets+headline", r and "Markets" in r["reply"]
              and "headline" in r["reply"].lower(), r and r["reply"][-260:])

        snap = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8595/api/markets").read())
        check("/api/markets", snap.get("ok") and snap.get("simulated"),
              snap.get("source"))

    passed = sum(1 for _, ok in results if ok)
    print(f"\n=== {passed}/{len(results)} passed ===")
    for n, ok in results:
        if not ok:
            print("FAILED:", n)


asyncio.run(main())
