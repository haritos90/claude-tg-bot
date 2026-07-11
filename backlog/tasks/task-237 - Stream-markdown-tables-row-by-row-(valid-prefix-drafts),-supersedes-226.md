---
id: TASK-237
title: "Stream markdown tables row-by-row (valid-prefix drafts), supersedes #226"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 237
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tables now build up row-by-row as a reply streams (header, then each row), in the same native style as the finished message — no broken partial grid and no snap at the end.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The real fix for the #226 table-streaming bug, CONFIRMED working on-device 2026-06-19. Grounding (verified against the official docs, captured in `rich-message-spec.md`): the streaming draft (`streamer._render_draft` → `sendRichMessageDraft {"markdown": frontier}`) and the final message (`_commit_rich_markdown` → `sendRichMessage {"markdown": full_text}`) use the SAME Rich Markdown renderer, so a COMPLETE table renders identically in both; the "first row only, snaps at finish" symptom was the draft carrying a table mid-row (a half-typed row/separator is invalid GFM → Telegram shows the header line alone). Fix: `markup.clip_partial_table` drops the in-progress trailing table line so every draft frame is a VALID prefix — the native table grows header→row→row with no snap, in the same style as the finished message. Rejected approaches kept COMMENTED with a #237 ref (the #162/#226-attempt-1 `<pre>` grid wraps on wide tables; the #226-attempt-2 placeholder hid the table). Also added the `/verify-rich-draft` command + `rich-message-spec.md` (verbatim doc extract) + `deploy/verify-rich-draft.py` (live API draft→final test, bypasses aiogram/streamer to isolate glitches) so future agents ground table/draft work in the spec instead of guessing. Pure helper `clip_partial_table` + unit tests (`tests/test_markup.py`); py_compile + ruff clean; full suite 161 passed (1 pre-existing PIL font failure); live restart confirmed "Run polling"; on-device confirmed row-by-row.
<!-- SECTION:NOTES:END -->

