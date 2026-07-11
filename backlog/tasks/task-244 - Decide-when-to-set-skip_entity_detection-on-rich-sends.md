---
id: TASK-244
title: "Decide when to set `skip_entity_detection` on rich sends"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 244
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Decide when to set `skip_entity_detection` on rich sends
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Won't do — not worth the per-send complexity; Telegram's auto entity-detection (URLs / mentions / hashtags) stays ON for every rich send. Revisit only if spurious linkification of file paths / @handles in output becomes a real problem.
<!-- SECTION:NOTES:END -->

