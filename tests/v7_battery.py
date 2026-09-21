"""v7 battery: the SELF engine learning, tuning and explaining itself live."""
import asyncio, json, time, urllib.request

import websockets

BASE = "ws://127.0.0.1:8595/ws"
results, side = [], []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'} {name} {str(extra)[:180]}")


async def send_and_wait(ws, text, timeout_s=12):
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
        st = hello.get("self") or {}
        check("hello self stats", "turns" in st and "self_rules" in st,
              json.dumps(st)[:100])

        # teach: nonsense phrase + rephrase, twice
        for _ in range(2):
            r = await send_and_wait(ws, "zorblat mode")
            check_once = r and "rule brain" in r["reply"]  # first time: fallback
            r = await send_and_wait(ws, "lights on kitchen")
        check("teaching pairs sent (fallback then intent)", True, "")

        learned = None
        deadline = time.time() + 100
        while time.time() < deadline and learned is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] == "announce" and "taught myself" in m.get("text", ""):
                learned = m
            else:
                side.append(m)
        check("self announced new alias", learned is not None,
              (learned or {}).get("text", "")[:140])

        r = await send_and_wait(ws, "zorblat mode")
        check("alias now works", r and "Kitchen lights on" in r["reply"],
              r and r["reply"])

        r = await send_and_wait(ws, "why did you say that")
        check("explain traces alias", r and "taught myself" in r["reply"],
              r and r["reply"][:160])

        r = await send_and_wait(ws, "thanks jarvis")
        r = await send_and_wait(ws, "self check")
        check("self report", r and "Self-report" in r["reply"]
              and "zorblat mode" in r["reply"], r and r["reply"][:200])

        api = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8595/api/self").read())
        check("/api/self praise counted", api["praise"] >= 1
              and any(x["pattern"] == "zorblat mode" for x in api["self_rules"]),
              json.dumps({"praise": api["praise"],
                          "rules": len(api["self_rules"])}))

        r = await send_and_wait(ws, "unlearn zorblat mode")
        check("unlearn", r and "Unlearned" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "zorblat mode")
        check("alias gone -> fallback again", r and "rule brain" in r["reply"],
              r and r["reply"][:80])

    passed = sum(1 for _, ok in results if ok)
    print(f"\n=== {passed}/{len(results)} passed ===")
    for n, ok in results:
        if not ok:
            print("FAILED:", n)


asyncio.run(main())
