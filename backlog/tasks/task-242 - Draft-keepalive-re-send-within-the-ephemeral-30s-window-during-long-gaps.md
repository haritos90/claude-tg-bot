---
id: TASK-242
title: "Draft keepalive: re-send within the ephemeral 30s window during long gaps"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 242
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "thinking"/working indicator and streamed text no longer vanish during a long tool call or pause — the draft is kept alive until the reply continues.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A draft is a ~30s ephemeral preview; if `_render_draft`'s content didn't change for that long (a static `<tg-thinking>` phase during a long tool run, or a mid-reply pause) the draft — and the indicator — expired, leaving only typing dots. Added `_DRAFT_KEEPALIVE_SECS` (20s): both draft paths (the thinking-placeholder branch and the content-frontier branch) now skip a send only when the content is unchanged AND it was sent < 20s ago; otherwise they re-send the same draft to keep it alive before the 30s expiry. The thinking branch now also stamps `_last_edit` on send. (Also: the thinking gerunds gained a 💭 prefix for a visible icon.) py_compile + ruff + suite (163) clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

