---
id: TASK-126
title: "`/permissions` gated to code sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 126
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Permissions menu only where it applies.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat is tool-free (the engine hardcodes `permission_mode="default"`), so `/permissions` + the `/settings` row now say "code only" / are hidden in chat.
<!-- SECTION:NOTES:END -->

