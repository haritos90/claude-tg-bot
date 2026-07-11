---
id: TASK-321
title: "Web-search Sources card disabled — search feedback is the animated thinking tag alone"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 321
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The web-search indicator is now just the native animated "🔎 Searching…" tag — no extra "Sources" message above the answer (the real source links the model gives in its answer are unaffected).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The live "Sources" card (#318/#319) is turned off: it listed the search QUERIES (mislabelled as "sources"), duplicated the real sources the model already cites as links in its answer, and read as message-clutter — the animated 🔎 thinking-tag (search-themed gerund rotation) already conveys "searching the web" natively. Commented out the card's call sites (the `tool`-branch wiring in `sessions.py` and the `finalize_sources()` call in `finish()`); the machinery (`add_web_source` / `finalize_sources` / `sources_card_markdown` + the `stream.searching` / `stream.sources_title` strings) is kept intact for an easy revert. The search animation, the `tool_start` early-phase signal, and the #320 pre-tool-text fix are unchanged. Parked the card's wiring test; the pure-render test stays. Updated `rich-message-spec.md` to record why the card was removed. compile + import + ruff + suite 236 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

