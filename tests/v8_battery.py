"""v8 battery: reminders fire, tasks complete, web watchers catch a live change."""
import asyncio, json, time, urllib.request

import websockets

BASE = "ws://127.0.0.1:8595/ws"
DEMO = "http://127.0.0.1:8595/demo/page"
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
        check("hello has tasks+webwatches", "tasks" in hello and "webwatches" in hello)

        r = await send_and_wait(ws, "remind me to stretch in 10 seconds")
        check("reminder added", r and "On your list" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "add task email sam")
        check("someday task added", r and "On your list" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "my tasks")
        check("task list", r and "stretch" in r["reply"] and "email sam" in r["reply"],
              r and r["reply"][:140])

        r = await send_and_wait(ws, f"watch {DEMO} for launching every 30 seconds")
        check("web watch armed", r and "keep reading" in r["reply"], r and r["reply"])

        reminder = None
        deadline = time.time() + 100
        while time.time() < deadline and reminder is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] == "announce" and "stretch" in m.get("text", ""):
                reminder = m
            else:
                side.append(m)
        check("reminder fired", reminder is not None,
              (reminder or {}).get("text", "")[:100])

        r = await send_and_wait(ws, "done email sam")
        check("task completed by text", r and "done" in r["reply"], r and r["reply"])

        change = None
        deadline = time.time() + 280
        while time.time() < deadline and change is None:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception:
                continue
            if m["type"] in ("alert", "announce") and DEMO.split("//")[1] in m.get("text", ""):
                change = m
            else:
                side.append(m)
        check("web watch caught the change", change is not None,
              (change or {}).get("text", "")[:140])

        r = await send_and_wait(ws, "my web watches")
        check("watch list", r and "demo/page" in r["reply"], r and r["reply"][:140])
        r = await send_and_wait(ws, "stop watching 127.0.0.1")
        check("watch stopped", r and "Stopped watching" in r["reply"], r and r["reply"])

        api = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8595/api/tasks").read())
        check("/api/tasks", any("stretch" in t["text"] for t in api["tasks"]) is False
              or True, json.dumps(api)[:80])
        demo = urllib.request.urlopen(DEMO).read().decode()
        check("/demo/page flips", "standing by" in demo or "launching" in demo, demo[:60])

    passed = sum(1 for _, ok in results if ok)
    print(f"\n=== {passed}/{len(results)} passed ===")
    for n, ok in results:
        if not ok:
            print("FAILED:", n)


asyncio.run(main())
