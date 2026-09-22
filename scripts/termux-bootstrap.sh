#!/data/data/com.termux/files/usr/bin/bash
# One-pipe phone joiner: installs what it needs, clones the repo, starts the
# agent, and wires Termux:Boot so the phone rejoins the fleet after reboots.
#   curl -fsSL <raw>/scripts/termux-bootstrap.sh | bash -s -- ws://<ip>:8595 <token>
set -euo pipefail
CORE="${1:?usage: termux-bootstrap.sh ws://<core>:8595 <token> [name]}"
TOKEN="${2:?missing token}"
NAME="${3:-$(getprop ro.product.model 2>/dev/null | tr ' ' '-' | tr 'A-Z' 'a-z' || echo phone)}"

pkg install -y git python >/dev/null 2>&1 || true
DIR="${JARVIS_DIR:-$HOME/jarvis}"
[ -d "$DIR/.git" ] || git clone -q -b "${JARVIS_BRANCH:-main}" \
  https://github.com/saistarayub-hash/JARVIS-PERSONAL "$DIR"
cd "$DIR"
[ -x .venv/bin/python ] || { python -m venv .venv && .venv/bin/pip install -q -U pip; }
.venv/bin/pip install -q websockets pyyaml requests

mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/jarvis-agent.sh" <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd $DIR
nohup .venv/bin/python -m jarvis.fleet.agent --name $NAME --url $CORE \\
  --token $TOKEN >> \$HOME/jarvis-agent.log 2>&1 &
BOOT
chmod 700 "$HOME/.termux/boot/jarvis-agent.sh"

echo "jarvis-phone: installed; boot link written; starting the agent now…"
echo "tip: install the Termux:Boot app from F-Droid and this joins after every reboot."
exec .venv/bin/python -m jarvis.fleet.agent --name "$NAME" --url "$CORE" --token "$TOKEN"
