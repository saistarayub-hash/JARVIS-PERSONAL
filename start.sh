#!/usr/bin/env bash
# JARVIS — run it now (Linux, macOS, Termux).
#
#   curl not needed; it clones the repo, makes a venv, installs deps,
#   wires the LLM key if you give one, and starts the core.
#
#   ./start.sh                        # interactive
#   JARVIS_KEY=*** ./start.sh           # non-interactive, real brain
#   JARVIS_KEY=*** ./start.sh --demo     # + simulated fleet devices
#   ./start.sh --service               # headless + autostart (systemd/launchd)
#
# Env: JARVIS_DIR (default ~/jarvis) · JARVIS_REPO · JARVIS_BRANCH (default main)
set -euo pipefail

say() { printf '\033[36mjarvis-setup:\033[0m %s\n' "$*"; }
die() { printf '\033[31mfailed:\033[0m %s\n' "$*" >&2; exit 1; }


BRANCH="${JARVIS_BRANCH:-main}"
REPO="${JARVIS_REPO:-https://github.com/saistarayub-hash/JARVIS-PERSONAL}"
DIR="${JARVIS_DIR:-$HOME/jarvis}"
KEY="${JARVIS_KEY:-}"
SERVICE=0
ARGS=()
for a in "$@"; do
  [ "$a" = "--service" ] && SERVICE=1 || ARGS+=("$a")
done

command -v git >/dev/null || die "git isn't installed — install it and re-run"
PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || die "python3 (3.10+) is required"
"$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "need Python 3.10+, found $("$PYBIN" -V 2>&1)"

# 1 — code
if [ -d "$DIR/.git" ]; then
  say "updating $DIR (branch $BRANCH)"
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" \
    && git -C "$DIR" merge --ff-only -q FETCH_HEAD || say "pull skipped (local edits?) — continuing with what's there"
else
  say "cloning $REPO -> $DIR"
  git clone -q -b "$BRANCH" "$REPO" "$DIR" || die "clone failed — check the URL/branch"
fi
cd "$DIR"

# 2 — venv + deps
if [ ! -x .venv/bin/python ]; then
  say "creating a virtualenv"
  "$PYBIN" -m venv .venv || die "python3 -m venv failed (apt install python3-venv on Debian/Ubuntu)"
fi
VPY=.venv/bin/python
say "installing dependencies (fastapi, uvicorn, websockets, …)"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt || die "pip install failed — network or proxy issue?"

# 3 — config + brain
[ -f config.yaml ] || { cp config.example.yaml config.yaml; say "config.yaml created from example"; }
if [ -z "$KEY" ] && [ ! -f .no_key_prompt ]; then
  if [ -t 0 ]; then
    printf 'Paste a Token Harbor key for the real LLM brain (leave blank to stay on the rule brain, or press it again to skip this prompt next time): '
    read -r KEY || KEY=""
    [ "$KEY" = "skip" ] && touch .no_key_prompt
  fi
fi
if [ -n "$KEY" ]; then
  "$VPY" scripts/set_llm_key.py "$KEY" && say "llm brain: tokenharbor deepseek-v4.1-flash:free enabled"
else
  "$VPY" scripts/set_llm_key.py --off 2>/dev/null || true
  say "no key — running the rule brain (fully capable, honest, zero cost)"
fi

# 4 — voice?
if [ "${JARVIS_VOICE:-}" = "1" ]; then
  say "installing the voice stack (this one is big)"
  "$VPY" -m pip install -q -r requirements-voice.txt || say "voice deps failed — continuing without voice"
  "$VPY" - <<'EOF'
import yaml, pathlib
p = pathlib.Path("config.yaml"); c = yaml.safe_load(p.read_text()) or {}
c.setdefault("jarvis", c).setdefault("voice", {})["enabled"] = True
p.write_text(yaml.safe_dump(c, sort_keys=False))
EOF
fi

# 5 — integrate / run
if [ "$SERVICE" = "1" ]; then
  say "installing autostart (systemd/launchd/Termux-boot aware) + the jarvis command"
  "$VPY" -m jarvis.cli install
  say "done. Core starts with login; UI at http://127.0.0.1:8595; 'jarvis <words>' anywhere."
  exit 0
fi
UIPORT=8595
for ((i=0; i<${#ARGS[@]}; i++)); do [ "${ARGS[$i]}" = "--port" ] && UIPORT="${ARGS[$((i+1))]}"; done
say "starting JARVIS core — hologram UI opens at http://127.0.0.1:$UIPORT"
exec "$VPY" run.py "${ARGS[@]+"${ARGS[@]}"}"
