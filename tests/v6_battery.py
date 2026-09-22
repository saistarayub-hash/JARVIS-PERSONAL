"""v6 battery: home, music, scenes, phone SMS/call, vision honesty, panels."""
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
        home = hello.get("home") or {}
        check("hello home+music+scenes", home.get("simulated") is True
              and hello.get("music") is not None
              and "good-morning" in (hello.get("scenes") or []),
              json.dumps(hello.get("scenes"))[:120])

        r = await send_and_wait(ws, "lights on kitchen")
        check("lights on", r and "Kitchen lights on" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "dim desk to 40")
        check("dim light", r and "40%" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "tv on")
        check("tv on", r and "TV on" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "set temperature to 24")
        check("climate", r and "24" in r["reply"], r and r["reply"])

        st = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8595/api/home").read())
        check("/api/home reflects", st["home"]["lights"]["kitchen"]["on"]
              and st["home"]["tv"]["on"]
              and st["home"]["climate"]["target"] == 24,
              json.dumps(st["home"]["climate"]))

        r = await send_and_wait(ws, "play focus music")
        check("music play", r and "Playing" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "what's playing")
        check("music status", r and "This is" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "next track")
        check("music next", r and "Skipped" in r["reply"], r and r["reply"])

        r = await send_and_wait(ws, "text sam: running late")
        check("sms via phone", r and "Sent from phone" in r["reply"], r and r["reply"])
        r = await send_and_wait(ws, "call mom")
        check("call via phone", r and "Calling mom from phone" in r["reply"],
              r and r["reply"])

        r = await send_and_wait(ws, "what am i looking at")
        check("vision honest without LLM",
              r and ("no vision-capable LLM" in r["reply"] or "Looking at" in r["reply"]),
              r and r["reply"][:140])

        # scene runs in background: statuses + final announce
        # scene runs in background: collect every reply it produces
        await ws.send(json.dumps({"type": "chat", "text": "good morning"}))
        replies = []
        end = time.time() + 25
        while time.time() < end:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 2))
            except Exception:
                if replies:
                    break
                continue
            if m["type"] == "reply":
                replies.append(m["reply"])
            elif m["type"] != "state":
                side.append(m)
        check("scene ack", any("On it" in x for x in replies), replies[:1])
        final = next((x for x in replies if x.startswith("All done")), None)
        check("scene final report", final is not None, (final or "")[:140])
        st = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8595/api/home").read())
        check("scene moved the house",
              st["home"]["lights"]["kitchen"]["on"] and st["music"]["playing"],
              json.dumps(st["music"])[:100])

    passed = sum(1 for _, ok in results if ok)
    print(f"\n=== {passed}/{len(results)} passed ===")
    for n, ok in results:
        if not ok:
            print("FAILED:", n)


asyncio.run(main())
