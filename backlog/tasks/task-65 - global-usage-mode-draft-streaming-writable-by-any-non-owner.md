---
id: TASK-65
title: "global usage-mode / draft-streaming writable by any non-owner"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 65
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
global usage-mode / draft-streaming writable by any non-owner
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Owner-gated the mutations: `/usage <mode>` rejects non-owners (`common.owner_only_usage`); the settings `usage` + `drafts` rows are hidden for guests and `_settings_apply` ignores their taps. `/stream` stays per-session.
<!-- SECTION:NOTES:END -->

