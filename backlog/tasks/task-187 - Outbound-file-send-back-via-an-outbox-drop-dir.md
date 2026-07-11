---
id: TASK-187
title: "Outbound file send-back via an `outbox/` drop-dir"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 187
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In a code session, ask the agent to drop a file in `outbox/` (e.g. `cp report.pdf outbox/` or save straight to `outbox/chart.png`) and it's sent to your chat as a photo/document when the turn ends — no more zipping the whole workdir with /export just to grab one chart. Or archive the whole workdir into outbox/ (`tar czf outbox/all.tar.gz --exclude=./outbox .`, up to 49 MB) to send everything at once as an /export alternative.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The only way to get an agent-CREATED file out was /export (zips the whole workdir). Added a per-session `outbox/` drop-dir: the agent copies a file there (`cp chart.png outbox/`) and the host delivers it to the chat after the turn, then removes it. Pieces: `engine` pre-creates `<cwd>/outbox/` in `_ensure_client` (code mode) and ALWAYS appends an `OUTBOX_INSTRUCTION` to the code system-prompt preset (alongside any owner memory) teaching the mechanism; `sessions._deliver_outbox` (called in `_worker` right after `_run_one`, OUTSIDE the turn-sem so uploads don't hold a concurrency slot) drains the dir — images → `send_photo`, else → `send_document` — with per-file size caps (5 MB image / 49 MB doc — the doc cap matches /export + the Telegram bot send limit so the agent can archive the whole workdir into outbox/ as an /export alternative) and a 10-file/turn count cap; too-big files are dropped with one aggregated note, overflow stays for the next turn. Round-trip verified under bubblewrap: the jailed uid-65534 agent writes into the root-owned 0700 workdir and the host reads/deletes the file. Chose the drop-dir (the ticket's recommended mechanism) over mtime-diff / auto-send. +3 tests, 125 green.
<!-- SECTION:NOTES:END -->

