"""v4 battery #2: screenshots, calendar CRUD, meeting-prep banner."""
import asyncio, json, time, urllib.request

import websockets

BASE = "ws://127.0.0.1:8595/ws"
results, side = [], []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'} {name} {str(extra)[:200]}")


async def send_and_wait(ws, text, drain_s=2.0, timeout_s=12):
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
        cal = hello.get("calendar", [])
        check("hello calendar", len(cal) >= 3, [e["title"] for e in cal])

        r = await send_and_wait(ws, "meetings today")
        check("meetings today", r and "Design sync" in r["reply"], r and r["reply"])

        r = await send_and_wait(ws, "screenshot web-01", drain_s=3)
        shot = next((m for m in side if m["type"] == "screenshot"), None)
        check("screenshot reply", r and "overlay" in r["reply"], r and r["reply"])
        check("screenshot broadcast", shot and shot.get("url"), json.dumps(shot or {})[:120])
        if shot:
            with urllib.request.urlopen(
                    urllib.request.Request("http://127.0.0.1:8595" + shot["url"])) as resp:
                body = resp.read()
            check("screenshot PNG served", resp.status == 200 and body[:4] == b"\x89PNG",
                  f"{len(body)} bytes")

        r = await send_and_wait(ws, "add a call with ops at 11 pm")
        check("add throwaway", r and "Added" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "cancel ops")
        check("cancel throwaway", r and "Cancelled" in r["reply"], r and r["reply"])

        prep = None
        deadline = time.time() + 330
        while time.time() < deadline and prep is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] == "prep" and "Design sync" in m.get("label", ""):
                prep = m
            else:
                side.append(m)
        check("meeting prep banner", prep is not None, json.dumps(prep or {})[:180])

        r = await send_and_wait(ws, "i have a meeting with priya at 4 pm")
        check("auto-learn meeting -> calendar", r and "calendar" in r["reply"].lower(),
              r and r["reply"])

        r = await send_and_wait(ws, "brief me")
        check("brief has calendar", r and "Next:" in r["reply"], r and r["reply"][:140])

    passed = sum(1 for _, ok in results if ok)
    print(f"\n=== {passed}/{len(results)} passed ===")
    for n, ok in results:
        if not ok:
            print("FAILED:", n)
    print("side types:", json.dumps([m["type"] for m in side])[:220])


asyncio.run(main())
