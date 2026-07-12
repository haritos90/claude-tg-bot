---
id: TASK-371
title: >-
  Heading demotion: collapse ABOVE-side blank run (complete task-368); streamer
  draft spacer + location-token test gaps
status: Done
assignee: []
created_date: '2026-07-12 10:17'
updated_date: '2026-07-12 10:37'
labels:
  - bug
dependencies: []
priority: low
ordinal: 9362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Low-severity rendering follow-ups surfaced while reviewing the voice batch. None blocking — Telegram collapses blank paragraphs, so the visible impact is cosmetic.

- markup.demote_headings ABOVE-side blank run (app/telegram/markup.py:429-437 _add_spacer, called at :463): task-368 collapses the model's own blank line(s) only on the BELOW side of a demoted heading (the skip_blank flag at :442/447). The ABOVE-side _add_spacer() only conditionally appends ONE blank and never collapses a pre-existing blank RUN already in `out`, so input like an intro paragraph followed by two blank lines and then a heading still emits an extra empty paragraph above the heading — the same defect task-368 tightened, mirrored to the other side. Fix: before the above-side _add_spacer(), drop trailing blanks (`while out and out[-1] == "": out.pop()`), or collapse the run inside the helper. This completes task-368 symmetrically.

- streamer draft trailing spacer (app/telegram/streamer.py:~675): the draft call site does not .strip() the demote_headings output, unlike the two final-commit sites (:1322, :1381). A streaming draft can therefore transiently render a demoted heading with its trailing U+00A0 spacer and nothing under it. Self-heals once body text streams in; transient/cosmetic; pre-existing from task-360. Fix (if addressed): flush the deferred BELOW spacer only on the next NON-blank line.

- location-token replacement has no test (tests/test_streamer.py): the token replacement from task-354 (streamer.py:~1142) is untested. Add a test with two or more LOCATION_TOKEN occurrences in the rich text, asserting each is replaced by the localized note with none left over.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 demote_headings collapses blank runs symmetrically on both sides of a demoted heading.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. (1) markup._add_spacer (app/telegram/markup.py) now pops a pre-existing blank RUN before inserting the gap, so a heading PRECEDED by 2+ blank lines gets a single spacer like the below side (completes #368 symmetrically). (2) The heading loop defers the BELOW spacer until real content follows (swallowing the intervening blank lines meanwhile) instead of flushing on the very next line with a skip_blank flag — so a heading that ends a streaming draft no longer trails a lone floating nbsp spacer. Both behaviors verified directly: an above-side blank run collapses to one gap, and a draft ending on a heading renders just the bold heading with no trailing spacer. (3) tests/test_streamer.py adds a test for _location_notes replacing every LOCATION_TOKEN with the localized note (multi-pin) plus the no-op empty case. Full suite 279 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
