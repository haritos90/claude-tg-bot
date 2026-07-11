---
id: TASK-340
title: "Spec doc voice: journal narrative + first-person in `rich-message-spec.md`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 340
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Spec doc voice: journal narrative + first-person in `rich-message-spec.md`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two spec-voice violations in `docs/rich-message-spec.md` (the spec is declarative present-tense, no changelog narrative): the newline-table preamble carried a changelog anecdote about a corrected assumption "about to drive the #310 migration the wrong way" — restated as the rule itself (a single `\n` is NOT honoured as a line break in either rich field; see the per-field table below), keeping the #310 cross-ref; and the code-block note ended first-person ("nothing to fix on our side") — dropped, since the preceding clause already states it is a client rendering choice, not a bot/API bug. Verified neither phrase remains in the spec. Docs only. compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

