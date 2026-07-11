---
id: TASK-73
title: "systemd unit drift"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 73
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
systemd unit drift
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`deploy/tg-bot.service` rebranded "Claude Telegram Bot"; install/enable/journalctl use `claude-tg-bot`; example paths → `/opt/claude-tg-bot`; hardening intact. README already consistent.
<!-- SECTION:NOTES:END -->

