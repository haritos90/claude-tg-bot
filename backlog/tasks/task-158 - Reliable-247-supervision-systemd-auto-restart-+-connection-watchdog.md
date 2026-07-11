---
id: TASK-158
title: "Reliable 24/7 supervision: systemd auto-restart + connection watchdog"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 158
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot self-heals on crashes and dropped Telegram connections, and starts on boot.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `watchdog.py` (dependency-free sd_notify): the bot sends READY=1, then WATCHDOG=1 only after a successful Telegram probe (get_me) every WatchdogSec/2; `bot.py` runs it as a task and cancels it on shutdown. Rewrote `deploy/tg-bot.service` for the real root install with Type=notify + WatchdogSec=180 + Restart=always + StartLimitIntervalSec=0 — force-restarts on a dropped/wedged Telegram connection, never gives up across long outages, restarts on boot. Added optional `deploy/claude-tg-bot-restart.{service,timer}` (daily clean restart vs leaks/stale claude auth). Installed + enabled on the host (replaces the bare manual process that died during the 2026-06-16 Telegram outage and never returned). Robust-startup follow-up: a flaky link exposed a Type=notify start flap (startup get_me timed out BEFORE READY → restart loop) — fixed by sending READY before any network I/O, making the startup get_me non-fatal on network errors, and time-bounding setup_commands; added `deploy/install-systemd.sh` (one-command install that adapts paths/user to the checkout).
<!-- SECTION:NOTES:END -->

