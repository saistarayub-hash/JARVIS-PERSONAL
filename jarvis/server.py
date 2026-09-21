"""FastAPI server: hologram UI + WebSocket + HTTP + fleet hub endpoint."""
from __future__ import annotations

import asyncio
import os
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .main import Jarvis

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def create_app(cfg: dict) -> FastAPI:
    jarvis = Jarvis(cfg)
    app = FastAPI(title="JARVIS")
    app.state.jarvis = jarvis
    min_uses = cfg["learner"].get("min_uses", 2)

    @app.on_event("startup")
    async def _startup():
        jarvis.set_event_loop(asyncio.get_running_loop())

        async def _proactive_loop():
            tick = 0
            while True:
                await asyncio.sleep(60)
                tick += 1
                try:
                    jarvis.maybe_proactive()
                    jarvis.maybe_preps()
                    jarvis.maybe_meeting_prep()
                    jarvis.maybe_rate_alerts()
                    jarvis.maybe_self()
                    # web watchers do blocking HTTP — never on the event loop
                    # (they may even fetch this very server: /demo/page)
                    await asyncio.to_thread(jarvis.maybe_tasks_web)
                    if tick % 5 == 0:  # sequence-learner every ~5 min
                        jarvis.maybe_sequence_suggestion()
                    if tick % 5 == 2:  # push fresh markets to open UIs
                        snap = await asyncio.to_thread(
                            jarvis.markets.snapshot, True)
                        if snap.get("ok"):
                            jarvis.broadcast({"type": "markets", **snap})
                except Exception:
                    pass

        asyncio.create_task(_proactive_loop())

    @app.get("/", response_class=HTMLResponse)
    async def _index():
        with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as fh:
            return fh.read()

    @app.get("/style.css")
    async def _css():
        return FileResponse(os.path.join(UI_DIR, "style.css"), media_type="text/css")

    @app.get("/app.js")
    async def _js():
        return FileResponse(os.path.join(UI_DIR, "app.js"), media_type="text/javascript")

    @app.get("/api/state")
    async def _state():
        return jarvis.state()

    @app.get("/api/markets")
    async def _markets():
        snap = jarvis.markets.snapshot()
        return snap

    @app.get("/api/home")
    async def _home():
        return {"home": jarvis.home.state(), "music": jarvis.music.status(),
                "scenes": jarvis.prep.routine_names() if jarvis.prep else []}

    @app.get("/api/self")
    async def _self():
        return jarvis.self_engine.stats()

    @app.get("/api/tasks")
    async def _tasks():
        return {"tasks": jarvis.memory.tasks_open()}

    @app.get("/api/webwatches")
    async def _webwatches():
        return {"watches": jarvis.memory.web_watches()}

    # ---------------- v9: push outbox, digest, browser ----------------
    @app.get("/api/push")
    async def _push():
        return {"status": jarvis.push.status(),
                "outbox": jarvis.memory.push_recent(8)}

    @app.post("/api/push/test")
    async def _push_test(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        text = str(body.get("text") or "JARVIS push test — if you can read "
                                      "this, the bridge works.")
        channel = body.get("channel")  # None -> every configured channel
        chans = [channel] if channel else None
        results = await asyncio.to_thread(jarvis.push.send, text, chans)
        return {"ok": True, "pushed": results}

    @app.get("/api/digest")
    async def _digest():
        return {"pending": jarvis.memory.digest_pending(),
                "count": jarvis.memory.digest_pending_count(),
                "window": jarvis._digest_window()}

    @app.post("/api/digest/deliver")
    async def _digest_deliver():
        report = await asyncio.to_thread(jarvis.digest_report, True)
        return {"ok": True, "report": report}

    @app.get("/api/browser")
    async def _browser():
        av = jarvis.browser.available()
        shots = []
        try:
            d = jarvis.browser.shots_dir
            if d.exists():
                shots = sorted((p.name for p in d.glob("*.png")),
                               reverse=True)[:6]
        except Exception:  # noqa: BLE001
            pass
        return {**av, "recent_shots": shots}

    @app.get("/demo/page")
    async def _demo_page():
        """A local page that flips state every 2 minutes, so web-watchers are
        exercisable even with no internet (watch THIS url in demos)."""
        import time as _t
        phase = int(_t.time() // 120) % 2
        state = "launching" if phase else "standing by"
        return HTMLResponse(
            f"<html><head><title>Demo status page</title></head><body>"
            f"<h1>Project X status: {state}</h1>"
            f"<p>Telemetry nominal. Phase {phase}. This page changes every "
            f"two minutes so JARVIS web-watchers have something honest to "
            f"watch offline.</p></body></html>")

    @app.get("/api/calendar")
    async def _calendar():
        now = time.time()
        evs = jarvis.memory.calendar_events(now - 3600, now + 86400)
        return {"events": [{"id": e["id"], "title": e["title"],
                            "start_ts": e["start_ts"], "end_ts": e["end_ts"],
                            "location": e["location"]} for e in evs]}

    @app.get("/api/learned")
    async def _learned():
        return {"facts": [f["text"] for f in jarvis.memory.facts()],
                "habits": jarvis.memory.habits(min_uses=min_uses),
                "activity": jarvis.memory.activity_today()}

    @app.post("/api/facts/clear")
    async def _clear_facts():
        return {"ok": True, "cleared": jarvis.memory.clear()}

    @app.get("/api/screenshots/{fname}")
    async def _screenshot(fname: str):
        import os
        from fastapi.responses import FileResponse
        safe = os.path.basename(fname)  # no traversal
        if jarvis.hub is None:
            return JSONResponse({"ok": False, "message": "no fleet"}, 404)
        path = os.path.join(jarvis.hub.screenshot_dir(), safe)
        if not safe.endswith(".png") or not os.path.isfile(path):
            return JSONResponse({"ok": False, "message": "not found"}, 404)
        return FileResponse(path, media_type="image/png")

    @app.get("/api/fleet")
    async def _fleet():
        return {"devices": jarvis.hub.summary() if jarvis.hub else []}

    @app.post("/api/transcribe")
    async def _transcribe(request: Request):
        """Browser push-to-talk: raw mic audio in, handled reply out."""
        if not jarvis.voice:
            return JSONResponse(
                {"ok": False,
                 "message": "Voice stack isn't running on this server (chat mode). "
                            "Run with voice enabled to transcribe mic audio."},
                status_code=503)
        data = await request.body()
        if not data:
            return JSONResponse({"ok": False, "message": "No audio received."},
                                 status_code=400)
        try:
            text = await asyncio.to_thread(jarvis.voice.transcribe_bytes, data)
        except Exception as exc:
            return JSONResponse({"ok": False,
                                 "message": f"Transcription failed: {exc}"},
                                 status_code=500)
        if not text:
            return {"ok": False, "message": "I didn't catch that — try again, louder or closer."}
        jarvis.push_user_text(text)
        result = await asyncio.to_thread(jarvis.handle, text)
        return {"ok": True, "heard": text, **result}

    @app.websocket("/ws")
    async def _ws(ws: WebSocket):
        await ws.accept()
        jarvis.attach(ws)
        try:
            await ws.send_json(jarvis.hello_payload())
            jarvis.maybe_proactive()  # already broadcast to this socket
            jarvis.maybe_preps()
            while True:
                msg = await ws.receive_json()
                mtype = msg.get("type")
                if mtype == "ping":
                    await ws.send_json({"type": "pong"})
                    continue
                if mtype == "prep_later" and jarvis.prep:
                    jarvis.prep.mark(msg.get("key", ""), "snoozed")
                    continue
                if mtype == "routine_save":
                    name = msg.get("name", "")
                    actions = msg.get("actions") or []
                    if name and actions and jarvis.memory.routine_exists(name) is False:
                        jarvis.memory.save_routine(name, actions, "learned")
                    jarvis.broadcast({"type": "announce",
                                      "text": f"Routine '{name}' saved. "
                                              f"Fire it with 'prep {name}' or "
                                              f"'take care of {name}'."})
                    continue
                if mtype == "routine_dismiss":
                    continue
                if mtype == "task_done":
                    jarvis.tasks.complete_and_push(m.get("id") or m.get("text"))
                    continue
                if mtype != "chat":
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                await ws.send_json({"type": "state", "state": "thinking"})
                result = await asyncio.to_thread(jarvis.handle, text)
                await ws.send_json({"type": "reply", **result})
                await ws.send_json({
                    "type": "learned",
                    "facts": [f["text"] for f in jarvis.memory.facts()],
                    "habits": jarvis.memory.habits(min_uses=min_uses),
                    "activity": jarvis.memory.activity_today(),
                })
        except WebSocketDisconnect:
            pass
        finally:
            jarvis.detach(ws)

    @app.websocket("/fleet/ws")
    async def _fleet_ws(ws: WebSocket, name: str = "", token: str = ""):
        """Agent endpoint: ?name=web-01&token=SECRET"""
        expected = (cfg.get("fleet") or {}).get("token", "")
        if not expected or not name or token != expected:
            try:
                await ws.close(code=4401)
            except Exception:
                pass
            return
        await ws.accept()
        device = None
        try:
            msg = await asyncio.wait_for(ws.receive_json(), 10)
            if msg.get("type") != "auth":
                raise ValueError("expected auth first")
            device, was_out = jarvis.hub.register(
                name, msg.get("os", "?"), msg.get("meta", {}))
            device._ws = ws
            if was_out > 90:
                jarvis.on_device_back(name, was_out)
        except Exception:
            try:
                await ws.close(code=4402)
            except Exception:
                pass
            return
        try:
            while True:
                m = await ws.receive_json()
                if m.get("type") == "heartbeat":
                    jarvis.hub.on_heartbeat(name, m.get("telemetry", {}))
                elif m.get("type") == "event":
                    jarvis.note_device_event(name, m.get("kind", "note"),
                                             m.get("data", {}))
                elif m.get("type") == "result":
                    jarvis.hub._resolve(m.get("id", ""), {
                        "ok": m.get("ok", True), "data": m.get("data", {}),
                        "message": m.get("message", "")})
                elif m.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            if device is not None:
                device._ws = None
            if jarvis.hub.mark_gone(name):
                jarvis.on_device_gone(name)

    return app
