---
id: TASK-368
title: >-
  Review nits: markup blank-paragraph, engine cap-estimate/style, flaky
  stall-test timing
status: Done
assignee: []
created_date: '2026-07-11 17:12'
updated_date: '2026-07-11 17:26'
labels:
  - bug
dependencies: []
priority: low
ordinal: 6362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Low-severity polish surfaced while reviewing the current batch. None blocking.

- app/telegram/markup.py:439 (demote_headings): a heading followed by two or more blank lines emits one extra blank paragraph (only the first trailing blank is consumed by the continue). Renders fine (Telegram collapses blank paragraphs); tighten if convenient.
- app/core/engine.py:~1162 (over_cap estimate): the over-cap estimate strips session_notes while the actual write builds from the raw blob; consistent today (the blob is always clean, so strip is a no-op) and only affects the trimmed-note message, never saved data. Add a one-line comment noting the clean-blob assumption to prevent future drift.
- app/core/engine.py:~1728: the guard "if _wait and _wait > 0" has a redundant "_wait and" (the > 0 test already implies truthy). Pure style.
- app/core/engine.py:~1122 (pre-existing, note only): user_level is frozen at construction, so a cached code session keeps the session-memory tool until the next rebuild picks up a demoted level. Per-topic notes only (no cross-topic bleed); cosmetic.
- tests/test_engine.py:~465 (test_reasoning_then_answer_does_not_false_timeout): pairs a 0.05s stall window with a 0.001s inter-event sleep and asserts no timeout; on a heavily loaded runner the 50ms wait_for could fire spuriously. Widen the stall window (e.g. 1s) or make the first inter-event sleep 0 to remove any flakiness.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. (1) markup.demote_headings: a skip_blank flag swallows the model's own blank line(s) right after a heading's BELOW nbsp spacer, so a heading followed by 2+ blank lines no longer emits an extra empty paragraph. (2) engine.py stall watchdog: "if _wait and _wait > 0" simplified to "if _wait > 0" (the > 0 test already implies truthy). (3) engine.py _remember_tool: a comment now notes session_notes is a single clean blob, so the over-cap estimate's .strip() matches what _apply_session_note concatenates. (4) tests/test_engine.py test_reasoning_then_answer_does_not_false_timeout de-flaked: stall window 0.05 -> 0.2s, pre-answer inter-event sleep 0.001 -> 0 (yield only), post-answer gap 0.2 -> 0.4s (kept > window so the disarm assertion still holds). Left as-is: the pre-existing user_level-frozen-until-rebuild behavior in engine._session_memory_on is cosmetic (per-topic notes only, no cross-topic bleed). Full suite 275 green, ruff clean.
<!-- SECTION:NOTES:END -->
