---
id: TASK-163
title: "Tables: narrow → text grid, wide → image (cards rejected)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 163
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Wide tables now arrive as a clean table image; narrow ones stay copy-pasteable text grids.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Telegram has **no native table** (verified vs the HTML-style doc: no `<table>` tag, no `table` MessageEntity), a wide `<pre>` grid wraps off the bubble, and a vertical "cards" layout reads poorly. So: `markup.split_image_tables` extracts WIDE tables (rendered width > `_TABLE_GRID_MAX_WIDTH`=46) and the streamer sends them as a **PNG** (`table_image.render_table_png` — DejaVuSansMono/Cyrillic, bordered, shaded bold header) via `send_photo`; NARROW tables stay aligned `<pre>` text grids inline. `streamer._commit` rewritten to emit ordered text+photo "sendables" (`_build_sendables`); cell emphasis (`**bold**`/`` `code` ``/`~~`) is stripped (a grid can't host it). Added `Pillow` dep + `table_image.py`. `_render_table_cards`/`_render_table_auto` kept (superseded — the rejected B/C card variants). Chosen via an in-Telegram A–E variant test. Unit-tested. Caveat: image text isn't selectable/copyable.
<!-- SECTION:NOTES:END -->

