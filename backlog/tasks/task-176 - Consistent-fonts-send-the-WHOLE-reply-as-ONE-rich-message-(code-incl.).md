---
id: TASK-176
title: "Consistent fonts: send the WHOLE reply as ONE rich message (code incl.)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 176
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every reply is one consistent rich message — native tables / lists / headings; code is monospace for now (until Telegram styles rich code), no more font jumping.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Replies were inconsistent — a code reply went fully classic (smaller text, `<pre>` table grid), a no-code reply was rich (bigger). Two fixes were built: (a) a per-segment split — non-code runs RICH, each code block CLASSIC `<pre><code>` (`_commit_mixed` + `markup.split_code_blocks`/`has_code_block`, +2 tests); (b) the chosen design — **ONE consistent rich message** (prose + tables + lists + code) rather than splitting into bubbles, accepting that code shows as plain **monospace** in rich (the client doesn't style `RichBlockPreformatted` yet, #174) and waiting for Telegram to fix it (then code styles with NO change). `streamer._commit` now always uses `_commit_rich_markdown`; the split path is kept un-called for a quick flip-back. Streaming is rich throughout. markup.md updated.
<!-- SECTION:NOTES:END -->

