---
id: TASK-148
title: "/help drifted from the command registry"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 148
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/help drifted from the command registry
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/help` is GENERATED from `commands.COMMANDS` (grouped by `help_group`, role-filtered); i18n keeps only the intro/footer/group headers.
<!-- SECTION:NOTES:END -->

