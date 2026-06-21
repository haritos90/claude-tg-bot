#!/usr/bin/env bash
# Install / refresh the Claude Telegram Bot as a systemd service with auto-restart
# + a connection watchdog. Idempotent — safe to re-run after a code change.
#
#   sudo deploy/install-systemd.sh                 # install + enable + start
#   sudo deploy/install-systemd.sh --with-timer    # also enable the daily restart timer
#
# It adapts the committed unit (deploy/tg-bot.service) to THIS checkout — its path,
# the invoking user, and that user's HOME — so it works wherever the repo lives.
# See README "Run it 24/7 with systemd" and watchdog.py for how the resilience works:
#   * Restart=always + StartLimitIntervalSec=0  → respawn on any crash/exit + on boot,
#                                                  never give up across long outages.
#   * Type=notify + WatchdogSec=180             → the bot pings systemd only after a
#                                                  successful Telegram probe; a >3-min
#                                                  blackout (dropped/wedged connection)
#                                                  → systemd force-restarts it.
set -euo pipefail

UNIT=claude-tg-bot.service
DEST=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo $0)." >&2; exit 1; }

# Repo dir = parent of this script's dir (resolve symlinks).
SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
PY="$PROJECT_DIR/.venv/bin/python"

# Run as the user that owns the checkout, so the service can read that user's
# ~/.claude subscription creds. Prefer the human who ran sudo, else the dir owner.
RUN_USER=${SUDO_USER:-$(stat -c '%U' "$PROJECT_DIR")}
HOME_DIR=$(getent passwd "$RUN_USER" | cut -d: -f6)
HOME_DIR=${HOME_DIR:-/root}

[ -x "$PY" ] || { echo "venv python not found at $PY — create it first:" >&2;
                  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }

echo "Installing $UNIT  (dir=$PROJECT_DIR  user=$RUN_USER  home=$HOME_DIR)"

# Render the committed unit with this install's paths/user/home (one source of truth:
# deploy/tg-bot.service holds the policy; we only patch the install-specific lines).
sed -E \
  -e "s|^User=.*|User=$RUN_USER|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" \
  -e "s|^ExecStart=.*|ExecStart=$PY -m app|" \
  -e "s|^Environment=HOME=.*|Environment=HOME=$HOME_DIR|" \
  -e "s|^Environment=PATH=.*|Environment=PATH=$HOME_DIR/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin|" \
  "$PROJECT_DIR/deploy/tg-bot.service" > "$DEST/$UNIT"

# Make the optional daily-restart timer available (enabled only with --with-timer).
cp "$PROJECT_DIR/deploy/claude-tg-bot-restart.service" "$DEST/" 2>/dev/null || true
cp "$PROJECT_DIR/deploy/claude-tg-bot-restart.timer"   "$DEST/" 2>/dev/null || true

# Stop any MANUAL copy first (a 2nd poller per token → 409). #302: with `-m app` the
# manual and service cmdlines look alike, so exclude the unit's own MainPID before killing.
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
