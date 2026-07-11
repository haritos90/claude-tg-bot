---
id: TASK-19
title: "terminal-faithful rendering with copyable `<pre>` code blocks"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 19
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
terminal-faithful rendering with copyable `<pre>` code blocks
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Delivered: `markup.md_to_html` emits `<pre>` for one-tap copy and `<pre><code class="language-x">` for fenced blocks with a language (label + highlighting); raw-split-then-render keeps every chunk's tags balanced (`split_markdown`).
<!-- SECTION:NOTES:END -->

