---
id: TASK-215
title: "/sandbox hub row hidden on chat sessions + /model accepted junk strings"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 215
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/sandbox is reachable from the settings hub in chat sessions, and /model rejects unknown names (shows the picker) instead of setting an invalid model.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
(1) Removed `sandbox` from settings_schema CODE_ONLY so the hub row shows on chat sessions too — the jail covers all sessions since #180 and the /sandbox command already had no mode gate. (2) /model now validates its arg against the known aliases + model ids and falls back to the picker on anything else, instead of silently storing a bogus model (`/model gpt4`). py_compile + registry assertion + pytest (31) + ruff.
<!-- SECTION:NOTES:END -->

