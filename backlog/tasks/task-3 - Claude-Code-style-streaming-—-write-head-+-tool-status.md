---
id: TASK-3
title: "Claude-Code-style streaming — write-head + tool-status"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 3
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Claude-Code-style streaming — write-head + tool-status
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`streamer.py` rewritten to a typewriter write-head: `update()` buffers text, a frame loop reveals it progressively and slides a rotating braille caret to the frontier (runs while buffered, spins in place when caught up / before the first token). Live tool-status, chunked/`.md` flush. Evaluated native `sendMessageDraft` — private-chat-only (`TEXTDRAFT_PEER_INVALID` in groups), unusable in the supergroup; write-head kept. See AGENTS §5 + #39.
<!-- SECTION:NOTES:END -->

