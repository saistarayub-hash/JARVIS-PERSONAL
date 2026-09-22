#!/usr/bin/env bash
# One-time setup: stash the brain key where start.sh finds it automatically.
# The key never lands in shell history or any repo.
#
#   bash scripts/save-key.sh              # prompts (hidden input)
#   bash scripts/save-key.sh thk_live_…   # or give it directly
set -euo pipefail
KEY="${1:-}"
if [ -z "$KEY" ]; then
  printf 'Token Harbor key (input hidden): '
  read -rs KEY; echo
fi
[ ${#KEY} -ge 12 ] || { echo "looks too short — nothing saved." >&2; exit 1; }
DIR="${XDG_CONFIG_HOME:-$HOME/.config}/jarvis"
mkdir -p "$DIR"
umask 077
printf '%s\n' "$KEY" > "$DIR/token"
chmod 600 "$DIR/token" 2>/dev/null || true
echo "saved to $DIR/token (mode 600). From now on:  bash <(curl -sL https://raw.githubusercontent.com/saistarayub-hash/JARVIS-PERSONAL/main/start.sh)"