#!/usr/bin/env bash
# Install or refresh the bot as a systemd service.
# - Run with sudo; --with-timer adds the daily restart timer
# - Idempotent; adapts the unit to this checkout's path and user
# - Restart=always respawns on crash and on boot
# - Type=notify watchdog restarts after a 3-minute Telegram blackout
set -euo pipefail

UNIT=claude-tg-bot.service
DEST=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo $0)." >&2; exit 1; }

# Repo dir is the script's parent, symlinks resolved.
SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
PY="$PROJECT_DIR/.venv/bin/python"

# Run as the checkout owner to read its claude credentials.
# - Prefer the invoking sudo user, else the dir owner
RUN_USER=${SUDO_USER:-$(stat -c '%U' "$PROJECT_DIR")}
HOME_DIR=$(getent passwd "$RUN_USER" | cut -d: -f6)
HOME_DIR=${HOME_DIR:-/root}

[ -x "$PY" ] || { echo "venv python not found at $PY — create it first:" >&2;
                  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements/base.txt" >&2; exit 1; }

echo "Installing $UNIT  (dir=$PROJECT_DIR  user=$RUN_USER  home=$HOME_DIR)"

# Render the committed unit with this install's paths.
# - Unit file holds policy; only install-specific lines patched
sed -E \
  -e "s|^User=.*|User=$RUN_USER|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" \
  -e "s|^ExecStart=.*|ExecStart=$PY -m app|" \
  -e "s|^Environment=HOME=.*|Environment=HOME=$HOME_DIR|" \
  -e "s|^Environment=PATH=.*|Environment=PATH=$HOME_DIR/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin|" \
  "$PROJECT_DIR/deploy/tg-bot.service" > "$DEST/$UNIT"

# Make the optional daily-restart timer available.
# - Enabled only with --with-timer
cp "$PROJECT_DIR/deploy/claude-tg-bot-restart.service" "$DEST/" 2>/dev/null || true
cp "$PROJECT_DIR/deploy/claude-tg-bot-restart.timer"   "$DEST/" 2>/dev/null || true

# Stop any manual copy first, avoiding duplicate pollers.
# - Manual and service cmdlines look alike
# - Exclude the unit's own MainPID before killing
SVC_PID=$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null || true)
pgrep -f 'python -m app' 2>/dev/null | grep -vx "${SVC_PID:-x}" | xargs -r kill 2>/dev/null \
  && echo "stopped a manual bot copy" || true

systemctl daemon-reload
systemctl enable --now "$UNIT"

if [ "${1:-}" = "--with-timer" ]; then
  systemctl enable --now claude-tg-bot-restart.timer
  echo "enabled the daily restart timer"
fi

echo "---"
systemctl --no-pager --full status "$UNIT" 2>/dev/null | sed -n '1,6p' || true
echo "Logs: journalctl -u $UNIT -f"
