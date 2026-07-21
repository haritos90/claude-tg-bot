---
id: TASK-381
title: >-
  Interleave commit: size-split an oversize prose segment so a >4096-char run is
  not dropped
status: Done
assignee: []
created_date: '2026-07-20 12:43'
updated_date: '2026-07-20 13:26'
labels:
  - ux
  - reliability
dependencies: []
priority: medium
ordinal: 19362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The interleave path (streamer._commit_rich_interleaved, task-373/374) sends each prose segment as one message with only a single-shot HTML fallback, so a segment longer than Telegram 4096-char limit is silently lost. A data-loss regression the pre-interleave flow did not have. Extends the interleave hardening tracked in task-375.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A prose run longer than the message limit adjacent to a pin, diagram, or wide table is delivered (size-split or sent as a document), not dropped
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
streamer._commit_rich_interleaved: on a failed single rich send the per-segment fallback now size-splits the prose run via markup.split_markdown (fence-repairing) and sends each <=SAFE_LIMIT piece as HTML, so a run longer than the message limit (RICH_LIMIT 32768) beside a pin/diagram/wide-table is delivered in parts instead of failing the 4096-capped HTML send and being dropped by _safe. The keypad rides the last piece; only the first piece keeps the segment notification. Splitting happens ONLY on failure, so the common large-single-bubble rich case is unchanged. Old single-HTML fallback kept commented with #381. New test test_commit_rich_interleaved_oversize_segment_splits_on_rich_failure forces the rich send to fail and asserts >1 HTML piece (each within HARD_LIMIT), the pin still delivered, and the keypad only on the last piece. Full suite 291 passed; ruff clean. Fold into task-375 when reworking the interleave commit.
<!-- SECTION:NOTES:END -->
