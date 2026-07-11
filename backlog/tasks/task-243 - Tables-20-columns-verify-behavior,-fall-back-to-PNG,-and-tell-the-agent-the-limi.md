---
id: TASK-243
title: "Tables >20 columns: verify behavior, fall back to PNG, and tell the agent the limit"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 243
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A table wider than 20 columns is now delivered as a clear image (with a note in the text) instead of breaking, and the assistant is told to expect that.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A native rich table caps at 20 columns (rich-message-spec.md:82). (b) GUARD: `markup.extract_wide_tables` pulls every >20-column markdown table out of the reply body, leaves a localized `stream.wide_table` note (en+ru) where it was, and `streamer._commit` sends the rich markdown then each wide table as a PNG photo (`table_image.render_table_png`); a render failure degrades to a `<pre>` grid via the new `_send_wide_table_image` so data is never lost. (c) MODEL: new `engine.TABLE_FORMAT_NOTE` appended to BOTH the chat and code system prompts states the 20-column limit and the PNG fallback so the model formats accordingly. (a) VERIFY: `deploy/verify-rich-draft.py --wide [--cols N]` sends an over-limit table draft+final for live owner confirmation; the guard makes the bot never emit an over-limit NATIVE table regardless of the client's raw behavior. Fixed the long-missing PNG font dependency: installed `fonts-dejavu-core` on the host and made `table_image._load_font` fall back to PIL's bundled font when the TTF is absent (this also fixes the previously pre-existing `test_table_image_renders_png_bytes` failure). +unit tests (`extract_wide_tables`, `table_col_count`). py_compile + import + i18n symmetry/placeholder parity + ruff clean; **full suite 173 passed (0 failures)**; live restart "Run polling".
<!-- SECTION:NOTES:END -->

