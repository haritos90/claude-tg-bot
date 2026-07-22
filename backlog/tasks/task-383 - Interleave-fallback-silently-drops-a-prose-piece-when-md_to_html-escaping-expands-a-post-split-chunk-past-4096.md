---
id: TASK-383
title: >-
  Interleave fallback silently drops a prose piece when md_to_html escaping
  expands a post-split chunk past 4096
status: Done
assignee: []
created_date: '2026-07-21 15:43'
updated_date: '2026-07-21 17:14'
labels:
  - ux
  - reliability
dependencies: []
priority: high
ordinal: 21362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The #381 per-segment fallback in streamer._commit_rich_interleaved sizes split pieces by SAFE_LIMIT raw markdown chars, then sends markup.md_to_html(piece) directly. HTML-escaping (& < > become entities) plus added tags can expand a <=3900-char raw chunk past Telegram's 4096 hard limit, so the send raises TelegramBadRequest, which _safe swallows with no log — the piece is silently dropped. This re-introduces, in a narrower form, the exact data-loss #381 set out to eliminate, and it is undiagnosable. The sibling HTML send paths (streamer.py:387, 404) avoid this by routing each raw chunk through markup.render_within_limit, which re-splits so every emitted HTML piece is <= HARD_LIMIT. Found reviewing the interleave hardening batch; extends task-375/381.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every emitted HTML piece in the interleave fallback is guaranteed <= Telegram 4096 hard limit (route each raw chunk through markup.render_within_limit, as the sibling paths do); a genuinely unsendable piece is logged, not silently dropped
- [x] #2 Keypad and notification are keyed off the FLATTENED HTML piece list (reply_markup only on the final HTML piece; this segment's notification only on the first), so the keying survives a raw chunk expanding into multiple HTML pieces
- [x] #3 The interleave oversize-segment test actually guards the per-piece keypad (the splitting segment must be the keypad-bearing one, so reverting p_kb to unconditional kb fails) and asserts piece/pin order plus that the oversize segment alone yields >=2 pieces
<!-- AC:END -->



## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. streamer._commit_rich_interleaved fallback (app/telegram/streamer.py): the per-segment fallback now flattens htmls = [h for raw in (split_markdown(md) or [md]) for h in markup.render_within_limit(raw)] and sends each HTML piece; render_within_limit re-splits + hard-cuts so every piece is <= HARD_LIMIT (the guard the sibling paths at :387/:404 use), eliminating the escaping-expansion silent drop. Keypad/notification keyed off the FLATTENED list (pi == len(htmls)-1 / pi == 0). A piece whose send still returns None is logged (logger.warning) instead of vanishing. Old raw-split fallback kept commented with #383. Test tests/test_streamer.py strengthened: the oversize run is now the LAST text segment so it BOTH splits AND carries the keypad — asserts lead/pin ordering, >=2 pieces for the oversize run, every piece <= HARD_LIMIT, and the keypad ONLY on the last piece (a revert to keypad-on-every-piece fails). Full suite 294 passed; ruff clean; restarted + Run polling.
<!-- SECTION:NOTES:END -->
