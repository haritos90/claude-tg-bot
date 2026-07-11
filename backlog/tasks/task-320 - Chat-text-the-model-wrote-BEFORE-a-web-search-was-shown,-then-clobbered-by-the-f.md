---
id: TASK-320
title: "Chat: text the model wrote BEFORE a web search was shown, then clobbered by the final answer"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 320
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When the bot says something before searching (e.g. "let me look that up") that line now stays as its own message instead of flashing and being rewritten — and the live search animation shows during the search.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Diagnosed from a live transcript: the model wrote a "let me clarify / meanwhile I'll search" line, ran two WebSearches, then wrote the real answer (text → tool → text). Because pre-tool text was committed as its own bubble only in CODE mode, in CHAT it was streamed and then OVERWRITTEN when the final result (which excludes the pre-tool text) was committed — and since it sat in the draft buffer the search animation never showed. Removed the code-only restriction on the tool-boundary `segment_break` (now both modes): pre-tool text is kept as its own message and the draft frees up so the search animation runs. No-op when there is no pre-tool text (the common "just search then answer"). +regression test (chat text → tool → text → one split, final = post-tool answer). compile + import + ruff + suite 237 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

