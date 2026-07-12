---
id: TASK-372
title: >-
  Hygiene: non-Latin test fixture in test_engine.py; first-person spec prose in
  markup.md/AGENTS.md
status: Done
assignee: []
created_date: '2026-07-12 10:17'
updated_date: '2026-07-12 10:37'
labels:
  - docs
dependencies: []
priority: medium
ordinal: 10362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two hygiene violations in the current batch.

- Non-Latin test fixture (English-only rule): tests/test_engine.py (test_apply_session_note_byte_accurate_cap, ~:127, added in this batch) uses a Cyrillic letter to build a 200-byte string for the UTF-8 byte-cap boundary test, with a comment stating the character count and byte count. The English-only rule permits non-Latin text only in the three translation surfaces (i18n.py ru values, commands.py ru labels, menu.md bilingual label tables) — tests are not exempt. Fix: use a neutral 2-byte UTF-8 character instead (e.g. U+00E9), which exercises the identical even-cap-on-boundary and odd-cap-splits-a-character behavior; the 4-byte emoji case already in the test is neutral and stays.

- First-person spec prose: docs/markup.md:~111 (a sentence describing the classic-HTML fallback) and AGENTS.md:~227 (a sentence describing the approval gate) use first person ("we"/"our"), breaking the declarative, no-first-person spec-voice rule. Both lines are pre-existing (outside this batch's diff hunks) but live in files the batch changes. Fix: reword in third person (e.g. "classic HTML is used as the fallback"; "the approval gate fires").
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No non-Latin literals remain in tests/test_engine.py.
- [ ] #2 markup.md and AGENTS.md spec prose is third-person.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. (1) tests/test_engine.py: the byte-cap fixture uses a neutral 2-byte character (U+00E9) instead of Cyrillic — the even/odd UTF-8 boundary math is identical, and the file is now free of non-Latin language literals (English-only rule). (2) docs/markup.md and AGENTS.md: the two first-person sentences ("we fall back" / "our gate fires") are reworded in third person ("classic HTML is used as the fallback" / "the approval gate fires"). Full suite 279 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
