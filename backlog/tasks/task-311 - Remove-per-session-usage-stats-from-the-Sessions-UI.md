---
id: TASK-311
title: "Remove per-session usage stats from the Sessions UI"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 311
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The session list and session cards are cleaner — no more per-session message/token counts cluttering the view; overall usage is still in /usage and /userstats.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `/sessions` list rows and the per-session card / options menu no longer show usage stats (messages · tokens · weighted-units). Commented out (with refs) the bulk-usage query + the padded msgs/tokens/units columns in `_render_sessions`, the per-row stats line, and the `reqs/toks` half of `session.card_meta` in `_session_card` / `_session_options`; retired the `sessions.row_stats` i18n key and dropped the `{reqs}/{toks}` placeholders from `session.card_meta` (both locales). Shared helpers are untouched — `get_usage_totals_bulk` (still used by the cap-evictor) and `_rpad_mono` (still used by `/userstats`); usage totals remain available via `/usage` and `/userstats`. compile + import + ruff + suite 230 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

