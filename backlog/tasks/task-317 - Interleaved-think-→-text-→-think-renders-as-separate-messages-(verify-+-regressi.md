---
id: TASK-317
title: "Interleaved think → text → think renders as separate messages (verify + regression test)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 317
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Verified that when the model thinks, answers, then thinks again, each step shows as its own message (thinking indicator → text → thinking indicator) — and locked it in with a test.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed the existing think-after-write handling is correct for the REPEATED case: each extended-thinking phase that follows answer text finalizes the prior text as its own bubble (`segment_break`) and re-opens a fresh `<tg-thinking>` block, so think → text → think → text → think streams as distinct messages and no later thinking phase is lost. Added a multi-cycle regression test (two interleaves → two splits, all three reasoning phases captured) alongside the existing single-cycle one. No code change needed — behavior already correct. compile + import + ruff + suite 234 clean.
<!-- SECTION:NOTES:END -->

