#!/usr/bin/env python3
"""JARVIS launcher.

    python run.py                 # full mode (voice if enabled in config.yaml)
    python run.py --no-voice      # chat mode only — no mic needed
    python run.py --demo          # spin up simulated fleet devices (web-01 + phone)
    python run.py --port 8600     # custom port

On each REAL device, connect it with the agent:

    python -m jarvis.fleet.agent --name web-01 --url ws://<core>:8595 --token <token>
"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import webbrowser

import uvicorn

from jarvis.config import load_config
from jarvis.server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="JARVIS — your personal AI butler")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-voice", action="store_true",
                    help="chat mode only, no microphone")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open the UI in a browser automatically")
    ap.add_argument("--demo", action="store_true",
                    help="join simulated fleet devices (web-01, phone) for demos")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    cfg["root"] = os.getcwd()
    if args.no_voice:
        cfg["voice"]["enabled"] = False

    host = args.host or cfg["web"]["host"]
    port = args.port or cfg["web"]["port"]
    app = create_app(cfg)

    if args.demo and app.state.jarvis.hub is not None:
        from jarvis.fleet.sim import SimAgent
        jarvis = app.state.jarvis
        jarvis.seed_demo_history()
        jarvis.seed_demo_calendar()
        app.state.jarvis._sim_agents = [
            SimAgent(jarvis.hub, "web-01", "Linux",
                     {"ip": "192.168.1.21", "role": "server"},
                     on_event=jarvis.note_device_event, jarvis=jarvis),
            SimAgent(jarvis.hub, "phone", "Android",
                     {"model": "Pixel 8", "role": "phone"},
                     on_event=jarvis.note_device_event, jarvis=jarvis),
        ]
        for a in app.state.jarvis._sim_agents:
            a.start()
        logging.getLogger("jarvis").info("demo fleet devices starting (web-01, phone)")

    if not args.no_browser:
        url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    if cfg["voice"]["enabled"]:
        from jarvis.voice.pipeline import VoicePipeline
        jarvis = app.state.jarvis
        jarvis.voice = VoicePipeline(jarvis, cfg["voice"], cfg["root"])
        jarvis.voice.start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
