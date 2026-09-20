"""Standing regression battery (v1-v3 behaviours)."""
import asyncio, json

import websockets

CASES = [
    ("hi", lambda a: "Boss" in a),
    ("what time is it", lambda a: ":" in a),
    ("what's the date", lambda a: "2026" in a),
    ("remember I deploy on Fridays", lambda a: "Noted" in a or "already" in a),
    ("12*(7+4)/2", lambda a: "66" in a),
    ("tell me a joke", lambda a: len(a) > 20),
    ("status of all devices", lambda a: "online" in a),
    ("status of web-01", lambda a: "web-01" in a),
    ("run docker ps on web-01", lambda a: "web-01" in a),
    ("run disk on phone", lambda a: "disk" in a.lower()),
    ("brief me", lambda a: "brief" in a.lower() or "Boss" in a),
    ("prep work", lambda a: "Opening" in a or "doesn't appear" in a or "terminal" in a.lower()),
    ("what do you know about me", lambda a: "file" in a.lower() or "Honest" in a),
]


async def main():
    ok = 0
    async with websockets.connect("ws://127.0.0.1:8595/ws") as ws:
        await ws.recv()  # hello
        for text, pred in CASES:
            await ws.send(json.dumps({"type": "chat", "text": text}))
            reply = ""
            while True:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 10))
                except Exception:
                    break
                if m["type"] == "reply":
                    reply = m["reply"]
                    break
            good = bool(pred(reply))
            ok += good
            print(("PASS" if good else "FAIL"), "|", text, "\n     ->", reply[:110])
    print(f"\n{ok}/{len(CASES)} passed")


asyncio.run(main())
