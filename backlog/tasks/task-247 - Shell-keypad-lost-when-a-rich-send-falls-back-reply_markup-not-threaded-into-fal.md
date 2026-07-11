---
id: TASK-247
title: "Shell keypad lost when a rich send falls back: `reply_markup` not threaded into fallback paths"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 247
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A paused shell command keeps its on-screen key keypad even when the rich message send falls back to the plain path.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`streamer.finish(reply_markup=...)` carries the #227b interactive-shell keypad, but `_commit` forwarded it only on the rich-markdown path. The fallback paths now thread it too: the long-output `send_document` branch passes `reply_markup`, and the legacy md_to_html chunk path attaches it to the FIRST text message via a `kb_pending` flag (consumed on the first `edit_message_text`/`send_message`, so it lands on exactly one bubble). A paused shell command driven through a fallback bubble keeps its keypad. py_compile + import + ruff clean; suite 167 passed (1 pre-existing PIL font failure); live restart "Run polling".
<!-- SECTION:NOTES:END -->

