#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="timepiece-watch.service"
PYTHON="$ROOT/.venv/bin/python"
TEMPLATE="$ROOT/deploy/timepiece-watch.service.in"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv at $PYTHON. Run setup from the README first." >&2
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing $ROOT/.env. Copy .env.example and set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID." >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
sed "s|__PROJECT_DIR__|$ROOT|g" "$TEMPLATE" > "$UNIT_DIR/$UNIT_NAME"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "$USER"
fi

echo "timepiece-watch is enabled and running."
echo "Status:  systemctl --user status timepiece-watch"
echo "Logs:    journalctl --user -u timepiece-watch -f"
echo "Stop:    systemctl --user stop timepiece-watch"
echo "Disable: systemctl --user disable --now timepiece-watch"
