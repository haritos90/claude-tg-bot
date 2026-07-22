---
id: TASK-387
title: >-
  Interleave surface: pre-existing robustness nits (footer-only keypad drop,
  mid-fence attachment split, silent pin loss)
status: In Progress
assignee: []
created_date: '2026-07-21 16:02'
updated_date: '2026-07-22 08:51'
labels:
  - ux
  - reliability
dependencies: []
priority: low
ordinal: 25362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Minor robustness gaps in _commit_rich_interleaved and its helpers, surfaced by a deeper review of the interleave commit. All P3; none introduced by the reviewed commit (pre-existing in the interleave/extract design).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 reply_markup (the keypad) is never dropped, including on an all-attachment reply (last_text_idx == -1)
- [ ] #2 An attachment token embedded inside a fenced code block does not produce prose segments with unbalanced fences
- [x] #3 A pin lost when both of its sends fail is logged, not silent
- [x] #4 The all-attachment trailing send checks the _safe return and logs a warning on a rejected send (parity with the fallback loop at streamer.py:1443 and _send_location at 1180), so a Telegram-rejected keypad/footer bubble is not silently lost; the U+2063 keypad-only carrier is confirmed accepted by Telegram or replaced with a known-good non-empty carrier
- [x] #5 The interleave fallback and _render_chunks skip is_empty_render blanks like _render_message_chunks (streamer.py:407), so a hard-cut inside a long single-line fence does not emit a blank tap-to-copy box
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
J and L implemented; K deferred. streamer.py: (J, AC1) the footer-only branch now fires on last_text_idx == -1 and (footer or reply_markup) and passes reply_markup, so the keypad is no longer dropped on an all-attachment reply (a keypad with no footer rides an invisible U+2063 carrier); (L, AC3) _send_location now logs a warning when both the venue and plain-pin sends fail, so a lost pin is no longer silent. Old code kept commented with #387. K (AC2 — an attachment token embedded inside a code fence yields prose segments with unbalanced fences) is DEFERRED: a safe fix needs a fence-balancing pass and no reusable balancer is exposed (the repair logic lives inside split_markdown, which also size-splits), so balancing every interleave segment risks the common path for a niche cosmetic case (data is not lost). Full suite 294 passed; ruff clean.

A follow-up review surfaced two more interleave nits (AC4/AC5). AC4: streamer.py:1453 — the all-attachment trailing send does not check the _safe return, unlike the fallback loop (1443) and _send_location (1180) which now warn on a drop, so a Telegram-rejected keypad/footer is silently lost; the U+2063 carrier used for a keypad-only reply is unverified against Telegram's empty-text check. AC5: streamer.py:1431 and 384 — the interleave fallback and _render_chunks do not filter is_empty_render (unlike _render_message_chunks at 407), so a hard-cut inside a long single-line fence can emit a blank pre bubble. Both are P3; none is data loss.

AC4/AC5 implemented (AC2 still deferred). streamer.py: (AC4) the all-attachment trailing send now captures _safe's result, retries a rejected keypad-only send once with a visible carrier, and logs a warning if it still fails, so a Telegram-rejected keypad/footer is no longer silently lost; (AC5) _render_chunks and the interleave fallback now skip is_empty_render blanks like _render_message_chunks, and the fallback keeps one carrier so the keypad still rides a real bubble.
<!-- SECTION:NOTES:END -->
