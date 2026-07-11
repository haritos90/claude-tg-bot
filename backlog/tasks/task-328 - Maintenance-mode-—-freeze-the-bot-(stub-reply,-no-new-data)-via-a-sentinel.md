---
id: TASK-328
title: "Maintenance mode — freeze the bot (stub reply, no new data) via a sentinel"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 328
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A maintenance switch: while it is on, users see a "back shortly" message and nothing they send creates data — so the owner can safely run a migration or other maintenance.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A `MAINTENANCE` sentinel file (toggled LIVE with `touch` / `rm`, checked per-update — no restart) puts the bot into maintenance: the access middleware (`AllowlistMiddleware`) replies a localized "🛠 back in ~15 min" stub to every allowed user and DROPS the update, so NO new session/turn data is created — built to freeze the dataset for the #327 migration cutover (and useful as a general maintenance switch). Owner-toggled from the shell (`touch /opt/claude-tg-bot/MAINTENANCE` / `rm`); checked before any handler so nothing creates data. +test (maintenance on → drop + stub, handler never runs; off → handler runs). compile + import + ruff + suite 242 clean; verified live (enabled → frozen → disabled).
<!-- SECTION:NOTES:END -->

