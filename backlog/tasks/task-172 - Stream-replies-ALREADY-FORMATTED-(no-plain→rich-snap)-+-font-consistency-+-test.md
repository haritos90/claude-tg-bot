---
id: TASK-172
title: "Stream replies ALREADY FORMATTED (no plain→rich snap) + font consistency + `/test`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 172
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replies generate already-formatted (no jarring switch); fonts are consistent across text commands; `/status` reads cleanly; `/test` lets the owner eyeball streaming; user stats reachable from the menu.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Bot API 10.1 `sendRichMessageDraft` streams a partial rich message that renders formatted AS it generates (Durov's GIF), persisted by the final `sendRichMessage` — `streamer._render_draft` now streams the raw markdown via it (plain-draft fallback on error). Verified live. Owner-only **`/test`** (last in the registry, not in `/`-menu or `/help`) simulates a streamed reply (3 paragraphs + 5×5 table + x86 asm snippet) via `sessions.stream_demo`. Consistency: `reply()` now sends command replies as rich too (matches `/status`/`/userstats`/streamed answers); `/status` restructured — flags as a `<ul>` checklist, usage windows + lifetime totals as `<ul>` lists, "Usage trend" relabelled "📈 Limit trend (recent utilization %)". Friendly name now also shows in the `/users` LIST (bold, before `@username`); `/userstats` reachable from the menu via a 📊 button on the Users page (shared `_send_userstats`).
<!-- SECTION:NOTES:END -->

