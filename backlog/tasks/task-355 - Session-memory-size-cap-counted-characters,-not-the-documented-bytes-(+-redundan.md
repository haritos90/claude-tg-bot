---
id: TASK-355
title: "Session-memory size cap counted characters, not the documented bytes (+ redundant recompute)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 355
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Session-memory size cap counted characters, not the documented bytes (+ redundant recompute)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_apply_session_note` documented its `cap` in bytes but measured with `len()` and sliced `blob[-cap:]` on Unicode code points, so a Cyrillic/CJK/emoji note could reach ~2-4× the 16 KB budget injected into the system prompt each turn. Now measures and slices on UTF-8 bytes (`blob.encode("utf-8")`, then `decode("utf-8", "ignore")` after the cut so a split multibyte char is dropped cleanly rather than mojibaked); the `db.set_session_notes` "bytes" docstring is now accurate. Also removed the redundant double-compute in `_remember_tool` — it called `_apply_session_note` a second time with `cap=10**12` purely to measure the untrimmed size; the untrimmed byte length is now derived directly from the inputs and the real call runs once. compile + import + ruff + suite 264 green (+ a focused byte-cap test: Cyrillic/emoji notes trimmed to the byte budget with a clean decode on even/odd/4-byte cuts); live restart "Run polling".
<!-- SECTION:NOTES:END -->

