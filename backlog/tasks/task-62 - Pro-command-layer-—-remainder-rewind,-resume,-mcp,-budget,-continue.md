---
id: TASK-62
title: "\"Pro\" command layer — remainder: `/rewind`, `/resume`, `/mcp`, `/budget`, `/continue`"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 62
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort L · deferred._

The safe subset shipped (#23). Remainder deferred after SDK introspection: `/rewind` needs `enable_file_checkpointing` + `replay-user-messages` + `UserMessage.uuid` capture (files-only); `/mcp` conflicts with the tool-free/isolation posture (code-mode only); `/budget` (`max_budget_usd`) is likely a no-op under subscription auth; `/resume`+`/continue` are redundant with the bot's own per-session resume.
<!-- SECTION:DESCRIPTION:END -->

