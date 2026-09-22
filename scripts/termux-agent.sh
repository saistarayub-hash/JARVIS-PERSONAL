#!/data/data/com.termux/files/usr/bin/bash
# JARVIS phone agent — run this inside Termux on Android to make the phone a
# real fleet device (screen capture, battery, SMS/call bridges on demand).
#
#   bash scripts/termux-agent.sh ws://192.168.1.20:8595 <token> [device-name]
set -euo pipefail
CORE="${1:?usage: termux-agent.sh ws://<core-host>:8595 <token> [name]}"
TOKEN="${2:?missing fleet token (the one in config.yaml fleet.token)}"
NAME="${3:-$(getprop ro.product.model | tr ' ' '-' | tr 'A-Z' 'a-z')}"
NAME="${NAME:-phone}"

pkg install -y python git >/dev/null 2>&1 || true
DIR="${JARVIS_DIR:-$HOME/jarvis}"
[ -d "$DIR/.git" ] || git clone -q -b "${JARVIS_BRANCH:-main}" \
  https://github.com/saistarayub-hash/JARVIS-PERSONAL "$DIR"
cd "$DIR"
[ -x .venv/bin/python ] || { python -m venv .venv && .venv/bin/pip install -q -U pip; }
.venv/bin/pip install -q websockets

say() { printf '\033[36mjarvis-phone:\033[0m %s\n' "$*"; }
say "waking termux extras (notifications, battery, vibrate are auto-used when present)"
say "agent starting: name=$NAME -> $CORE   (Ctrl-C to stop)"

# allow sms/call bridges only if the user exported the flags before running
EXTRA=""
[ "${JARVIS_ALLOW_SMS:-}" = "1" ] && EXTRA="$EXTRA --allow sms"
[ "${JARVIS_ALLOW_CALL:-}" = "1" ] && EXTRA="$EXTRA --allow call"

exec .venv/bin/python -m jarvis.fleet.agent --name "$NAME" --url "$CORE" \
     --token "$TOKEN" ${EXTRA:+$EXTRA}
