---
id: TASK-10
title: "systemd unit hardening (Restart=always, resource limits, basic sandboxing)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 10
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
systemd unit hardening (Restart=always, resource limits, basic sandboxing)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Hardened `deploy/tg-bot.service`: `ProtectSystem=strict` + `ReadWritePaths` (workdir, db, `~/.claude`), `PrivateTmp`, `MemoryMax`, `NoNewPrivileges`; added the REQUIRED `HOME`/`PATH` env so the `claude` CLI is found + creds reachable under systemd. The host install (`/etc/systemd/system`) is run by the owner.
<!-- SECTION:NOTES:END -->

