---
id: TASK-164
title: "Native Telegram tables (Bot API 10.1 `sendRichMessage`) + usage split"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 164
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tables render natively and side-scroll; users see their own limits, the owner sees global usage + a per-user stats table.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Supersedes #163's PNG/`<pre>` table. Bot API 10.1 `InputRichMessage.html` renders a real `<table>` (bordered/striped, `<th>`, colspan/rowspan, align/valign, `<caption>`); aiogram 3.28 has no binding so `rich_message.py` hand-declares `SendRichMessage(TelegramMethod)`. `markup.split_rich_tables` + `table_to_rich_html` route EVERY table natively (alignment from the `:--:` row, inline `<b>`/`<code>` kept); `streamer._send_rich` falls back to the `<pre>` grid on any failure (table never lost). PNG (`table_image.py`) + grid paths kept commented for revert. Usage rework: `/userstats` (owner, native table), `/limits` (user→own rolling limits, owner→real account usage), account footer gated **owner-only**, working-plate note (user limit ≥50% / owner account), **delegated** `hot_cache_timer` toggle + static post-reply warm-cache note, **hidden** owner-only `auto_compact` toggle (persist-only). DB: `hot_cache_timer`/`auto_compact` cols + `get_all_users_usage`. Verified live (probe + a 13-category rich-formatting showcase all accepted by the API). Docs: new `markup.md` + README/menu cross-refs. Follow-ups split to #165–#169.
<!-- SECTION:NOTES:END -->

