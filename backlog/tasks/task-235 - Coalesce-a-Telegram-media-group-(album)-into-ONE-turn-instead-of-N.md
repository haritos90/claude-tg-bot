---
id: TASK-235
title: "Coalesce a Telegram media-group (album) into ONE turn instead of N"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 235
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sending several files/photos at once (a Telegram album) is now handled as a single message — the bot reads them together and replies once, instead of firing a separate answer per file.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Telegram delivers an album as separate updates sharing a `media_group_id`, so `on_photo`/`on_document` fired once per item → N independent turns (a 4-file album = 4–5 turns) and the model never saw the files together. Added a debounce coalescer in `handlers.build_router`: the attachment handlers now route through `_route_attachment`, which for a `media_group_id` buffers each item in `album_buf` keyed by `(chat, thread, media_group_id)` and (re)arms an `ALBUM_DEBOUNCE_SECS` (0.8 s) timer; when it fires, `_flush_album` submits ONE turn. The session-key await is resolved before the get-or-create so concurrent item handlers can't double-create the buffer (no await inside the mutation). Combining math is the pure, unit-tested `_combine_album_parts` (sorts by message_id, concatenates image/PDF blocks, joins text/code `--- name ---` segments under one caption header, caps combined inline at MAX_TEXT_INLINE_CHARS, caps count at MAX_ALBUM_ITEMS=20 with a no-silent-truncation dropped note via new `attach.album_dropped` i18n key). Standalone (non-album) attachments are unchanged. v1 keeps a caption sent as a separate text message as its own turn. Added `tests/test_handlers.py` (4 cases). py_compile + import + ruff clean; full suite 159 passed (1 pre-existing unrelated PIL font failure); live restart confirmed "Run polling".
<!-- SECTION:NOTES:END -->

