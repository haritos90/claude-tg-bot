---
id: TASK-70
title: "long single-line code block emitted empty `<pre></pre>` messages"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 70
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
long single-line code block emitted empty `<pre></pre>` messages
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `markup.is_empty_render`; the streamer skips empty code-box chunks in `_commit` + `_render_message_chunks` (keeps the `…` floor for a genuinely empty turn). Test added.
<!-- SECTION:NOTES:END -->

