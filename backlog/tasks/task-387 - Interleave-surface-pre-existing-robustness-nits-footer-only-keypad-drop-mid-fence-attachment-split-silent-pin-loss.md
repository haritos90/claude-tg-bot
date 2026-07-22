---
id: TASK-387
title: >-
  Interleave surface: pre-existing robustness nits (footer-only keypad drop,
  mid-fence attachment split, silent pin loss)
status: In Progress
assignee: []
created_date: '2026-07-21 16:02'
updated_date: '2026-07-21 17:14'
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
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
J and L implemented; K deferred. streamer.py: (J, AC1) the footer-only branch now fires on last_text_idx == -1 and (footer or reply_markup) and passes reply_markup, so the keypad is no longer dropped on an all-attachment reply (a keypad with no footer rides an invisible U+2063 carrier); (L, AC3) _send_location now logs a warning when both the venue and plain-pin sends fail, so a lost pin is no longer silent. Old code kept commented with #387. K (AC2 — an attachment token embedded inside a code fence yields prose segments with unbalanced fences) is DEFERRED: a safe fix needs a fence-balancing pass and no reusable balancer is exposed (the repair logic lives inside split_markdown, which also size-splits), so balancing every interleave segment risks the common path for a niche cosmetic case (data is not lost). Full suite 294 passed; ruff clean.
<!-- SECTION:NOTES:END -->
