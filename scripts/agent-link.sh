#!/usr/bin/env bash
# Prints the EXACT command to run in Termux on your phone — LAN IP and fleet
# token read from the live config, no manual transcription.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${VPY:-.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
exec "$PY" scripts/agent_link.py
