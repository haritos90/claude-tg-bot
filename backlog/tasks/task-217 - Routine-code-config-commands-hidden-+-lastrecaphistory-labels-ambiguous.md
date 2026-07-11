---
id: TASK-217
title: "Routine code-config commands hidden + last/recap/history labels ambiguous"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 217
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code users now see /permissions, /tools and /secret in the command menu, and /recap vs /last vs /history are clearer.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Surfaced /permissions, /tools and /secret into the "/" menu for code users (were in_menu=False, only typeable). Clarified the session-content trio: /recap = one-line AI recap, /last = verbatim last exchange, /history = full transcript file. Dropped "code" from the /sandbox label (it applies to all sessions). py_compile + registry assertion + ruff.
<!-- SECTION:NOTES:END -->

