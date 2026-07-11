---
id: TASK-308
title: "`/users`: monospace per-user usage, friendly-name-only stats table, interactive user-card link"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 308
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In `/users`, the per-user usage columns line up for easy comparison, the stats table shows clean friendly names, and the user card's name is now a tappable link to that person's Telegram profile.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three `/users`-surface fixes. (1) The per-user usage lines in the `/users` list are now monospace and NBSP-padded so the 5h/week/total columns line up across users for comparison (`users.entry_usage`/`users.entry_usage_tok` wrapped in a WHOLE-LINE `<code>` — label included, matching the /sessions stat row so it renders as one monospace span — values padded via the new `_rpad_mono`; labels shortened; the shorter per-line label (units) gets a trailing NBSP after its colon so the units- and tokens-row columns line up vertically too). (2) The `/userstats` table shows ONLY the friendly name (no `@username` link), falling back to the id when none is set (`_plain_who`). (3) The user-card identity is now an INTERACTIVE link — the friendly name plus a clickable link to the user's Telegram profile (`https://t.me/<username>`, else `tg://user?id=<id>`), no longer plain text in parentheses; falls back to the id. The card title dropped its `<code>` wrapper and is sent without re-escaping (the link is pre-built, escaped HTML). compile + import + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

