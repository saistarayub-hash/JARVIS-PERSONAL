"""v9 battery: push outbox honesty, digest intents, browser fallback, and a
live proactive alert travelling through the new announce() router."""
import asyncio, json, time, urllib.request

import websockets

BASE = "ws://127.0.0.1:8595/ws"
API = "http://127.0.0.1:8595"
DEMO = "http://127.0.0.1:8595/demo/page"
results, side = [], []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'} {name} {str(extra)[:180]}")


def api(path, method=None):
    req = urllib.request.Request(API + path, method=method or "GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


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
    hello = None
    async with websockets.connect(BASE) as ws:
        hello = json.loads(await ws.recv())
        check("hello has push+digest+browser",
              "push" in hello and "digest" in hello and "browser" in hello,
              {k: hello.get(k) for k in ("push", "digest")})

        r = await send_and_wait(ws, "push status")
        check("push status honest",
              r and "not configured" in r["reply"] and "telegram" in r["reply"],
              r and r["reply"][:160])

        r = await send_and_wait(ws, "send Hello Sir to telegram")
        check("push_send logged simulated",
              r and "outbox" in r["reply"].lower() and "Nothing left" in r["reply"],
              r and r["reply"][:160])
        box = api("/api/push")
        entry = next((o for o in box["outbox"] if o["text"] == "Hello Sir"), None)
        check("outbox entry real+case-preserved",
              entry and entry["simulated"] == 1 and entry["channel"] == "telegram",
              entry)

        r = await send_and_wait(ws, "what did I miss")
        check("digest answers",
              r and ("quiet night" in r["reply"] or "Overnight digest" in r["reply"]),
              r and r["reply"][:160])

        r = await send_and_wait(ws, f"render {DEMO} in browser")
        check("browser fallback labelled plain-text",
              r and "plain-text read" in r["reply"] and "NOT rendered" in r["reply"]
              and ("aunching" in r["reply"] or "tanding by" in r["reply"]),
              r and r["reply"][:200])

        b = api("/api/browser")
        check("/api/browser states reason", b.get("ok") is False and "playwright" in b.get("reason", ""), b)
        d = api("/api/digest")
        check("/api/digest shape", isinstance(d.get("count"), int) and isinstance(d.get("window"), bool), d)
        dr = api("/api/digest/deliver", method="POST")
        check("digest deliver endpoint", dr.get("ok"), dr and dr.get("report", "")[:90])

        # live: arm a change-watch; the alert must travel announce()->UI intact
        r = await send_and_wait(ws, f"monitor {DEMO} every 30 seconds")
        check("change-watch armed", r and "keep reading" in r["reply"], r and r["reply"][:120])
        fired = None
        deadline = time.time() + 260
        while time.time() < deadline and fired is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] == "announce" and "demo/page" in m.get("text", ""):
                fired = m
            else:
                side.append(m)
        check("live alert through announce() router", fired is not None,
              (fired or {}).get("text", "")[:160])
        await send_and_wait(ws, "stop watching 127.0.0.1")
        check("watch cleaned up", api("/api/webwatches")["watches"] == [] or
              all(w.get("active", 0) == 0 for w in api("/api/webwatches")["watches"]))

    print(f"=== {sum(1 for _, ok in results if ok)}/{len(results)} passed ===")
    return all(ok for _, ok in results)


ok = asyncio.run(main())
raise SystemExit(0 if ok else 1)
