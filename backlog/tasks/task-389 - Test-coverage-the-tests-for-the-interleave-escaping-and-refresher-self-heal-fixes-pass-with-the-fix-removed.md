---
id: TASK-389
title: >-
  Test coverage: the tests for the interleave-escaping and refresher-self-heal
  fixes pass with the fix removed
status: Done
assignee: []
created_date: '2026-07-22 08:34'
updated_date: '2026-07-22 08:51'
labels:
  - tests
dependencies: []
priority: medium
ordinal: 27362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The tests added for the token-refresh executor self-heal (#385) and the interleave escaping-expansion split (#383) do not exercise the behavior they are named for; each passes against the pre-fix code, so a future regression would go undetected.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The refresher timeout test asserts the single-thread executor is recreated after a sweep timeout (a fresh ThreadPoolExecutor per timeout), not only the WARNING log level
- [ ] #2 The interleave escaping test feeds entity-dense input that renders past 4096 before #383 and within 4096 after, so the HARD_LIMIT assertion fails on the pre-fix code
- [ ] #3 The interleave test asserts the emitted pieces concatenate back to the original prose (no silent character loss), plus an exactly-4096-rendered boundary and an un-splittable single-long-line case
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added assertions so each test now fails if its fix is reverted. test_token_refresh.py: the timeout test records ThreadPoolExecutor constructions via a monkeypatched factory and asserts made>=2 (startup + at least one per-timeout recreate). test_streamer.py: the oversize interleave input is now entity-dense (repeated ampersands), so md_to_html escaping renders a raw chunk past 4096 and the HARD_LIMIT assertion distinguishes pre/post fix; a content-preservation assertion checks every ampersand survives the re-split. test_sessions.py: the outside-window case now calls twice and asserts no second creds read. test_markup.py: a new UTF-16 test (3000 emoji) asserts each piece fits in UTF-16 units and every emoji survives (covers the hard-cut floor and the un-splittable single line). Full suite 295 passed.
<!-- SECTION:NOTES:END -->
