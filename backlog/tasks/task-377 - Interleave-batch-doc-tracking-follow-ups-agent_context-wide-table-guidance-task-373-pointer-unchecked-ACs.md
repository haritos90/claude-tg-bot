---
id: TASK-377
title: >-
  Interleave batch doc/tracking follow-ups: agent_context wide-table guidance,
  task-373 pointer, unchecked ACs
status: To Do
assignee: []
created_date: '2026-07-15 19:39'
labels: []
dependencies: []
priority: low
ordinal: 15362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Documentation and tracking cleanups left by the #373/#374 interleave batch.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 agent_context.md wide-table guidance reflects the in-place interleave
- [ ] #2 task-373 notes point forward to the #374 rename
- [ ] #3 Neither Done task has dangling unchecked acceptance criteria
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
app/core/agent_context.md -- the wide-table guidance still states wide tables are sent as an image automatically, which implies end-batching; #374 now interleaves them at their token spot like the <svg> and location paragraphs. Extend that sentence so the model knows tables embed in place.
backlog task-373 Implementation Notes reference the method _commit_rich_with_pins() and tests test_commit_rich_with_pins_* that #374 (the same commit) renamed to _commit_rich_interleaved and test_commit_rich_interleaved_*. Add a forward pointer to #374 so a standalone reader does not grep for vanished symbols.
task-373 and task-374 are status Done yet each still carries three unchecked acceptance criteria that are in fact satisfied in code. Check them off, or drop the AC block, to match the Done convention.
<!-- SECTION:NOTES:END -->
