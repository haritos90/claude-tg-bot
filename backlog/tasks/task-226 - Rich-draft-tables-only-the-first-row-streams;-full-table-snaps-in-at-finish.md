---
id: TASK-226
title: "Rich-draft tables: only the first row streams; full table snaps in at finish"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 226
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
While a reply streams, a table is shown via the #237 row-by-row approach (the #226 placeholder/grid attempts were reverted).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
While streaming, `_render_draft` (`streamer.py`) pushed the frontier as a rich-markdown draft (`SendRichMessageDraft {"markdown": …}`, #172); Telegram's rich renderer shows a still-incomplete markdown table as only its first row, then the native rich table snapped in at `finish()`. A first attempt rendered the table frontier as a `<pre>` grid (`md_to_html`/`_tables_to_pre`) — but a WIDE multi-column table wraps to mush on a phone, so that regressed the look (confirmed on-device). Final approach: while a (possibly partial) table is in the frontier, `_render_draft` replaces it with a compact placeholder line via the new pure `markup.placeholder_tables` (detected by `markup.contains_table` — a ` | ` row followed by a GFM or ASCII separator, firing even on a partial header+separator) and keeps streaming the surrounding prose as a rich-markdown draft; `finish()` renders the real table via the native rich-table path (#164). Dedup now keys on the actually-sent draft text. try/except plain-HTML fallback retained so streaming never goes dark. SUPERSEDED by #237: the placeholder was rejected on-device (it hides the table instead of revealing it row-by-row), and the grid attempt re-did the already-rejected #162 grid. The real fix (clip in-progress rows so the draft is a valid growing prefix) is tracked and implemented in #237; the #226 helpers `contains_table`/`placeholder_tables` and their tests are kept COMMENTED with a #237 ref.
<!-- SECTION:NOTES:END -->

