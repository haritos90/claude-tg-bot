---
id: TASK-339
title: "Rich `{\"markdown\"}` cards collapsed multi-line content onto one line (todo card, usage footer, /status)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 339
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Multi-line cards — the live task list, the usage footer under a reply, and /status — show each line on its own line again instead of running together.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The verified rich-field newline rule (a single `\n` is a SOFT break = space; only `<br>` in html / `  \n` two-trailing-spaces in markdown / block constructs break a line) was not applied in three bot-composed rich sends, so their lines collapsed onto one: (1) the live TodoWrite card (`summarize_todos` joined glyph lines with `\n`; `update_todo_card` joined header→body with `\n`) ran every task onto one line; (2) the 2-line usage footer (`streamer`, 2 sites) collapsed to one; (3) `/status` (`reply_rich_html`, which sent raw `{"html"}` with no transform) glued its section headers onto the previous line. Fixes: join the todo lines + header with the markdown HARD break `  \n`; join the footer lines with `  \n`; add the `\n`→`<br>` transform to `reply_rich_html` (like `_send_menu` #202; classic fallback keeps raw `\n`). Each verified against the server-parsed `rich_message.blocks` (now one line each). +regression test (todo body uses `  \n`). Surfaced while comparing the html vs markdown rich fields for #310; rules recorded in `docs/rich-message-spec.md`. compile + import + ruff + suite green; live restart (`Run polling`).
<!-- SECTION:NOTES:END -->

