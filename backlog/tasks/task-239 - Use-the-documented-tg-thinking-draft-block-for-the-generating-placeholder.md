---
id: TASK-239
title: "Use the documented `<tg-thinking>` draft block for the generating placeholder"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 239
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "generating" placeholder uses Telegram's native animated Thinking block.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Replaced the empty plain "Thinking…" draft with the documented `<tg-thinking>` RichBlockThinking block (`_THINKING_HTML`), sent via `sendRichMessageDraft` in `start()` + the segment reset. Draft-only by construction (finish() uses `{"markdown"}`). Built on by #240 (animated gerunds + live tool phases). Confirmed on-device ("thinking/pondering" visible). py_compile + ruff + i18n clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

