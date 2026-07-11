---
id: TASK-11
title: "code snippets weren't copyable (the real ask behind \"telegramify backend\")"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 11
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
code snippets weren't copyable (the real ask behind "telegramify backend")
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Root cause (diagnosed by sending the owner a live A/B/C test message): the client copies only the tapped token, never a whole `<pre>` block. Fix: render each fenced code block as its **own message** (`markup.segment_blocks` + `streamer._render_message_chunks`) so long-press → Copy grabs the whole snippet. Also added `~~~` fence support. `telegramify-markdown` NOT adopted — the hand-rolled HTML renderer (copyable `<pre>`, language labels, fence-safe splitting) is better-controlled; closing the dep as won't-do.
<!-- SECTION:NOTES:END -->

