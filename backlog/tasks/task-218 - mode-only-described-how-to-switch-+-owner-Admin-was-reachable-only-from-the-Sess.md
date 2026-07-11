---
id: TASK-218
title: "/mode only described how to switch + owner Admin was reachable only from the Session tab"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 218
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/mode now switches the session type directly; the owner Admin page is also reachable from the Global settings tab.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
(a) /mode now TOGGLES the session type (chat ⇄ code) via `_switch_session_mode` instead of only printing how to switch (code access still gated). (b) Surfaced the owner Admin sub-page (global session limit, archive retention, global toggles) on the GLOBAL settings tab in addition to the Session tab. py_compile + registry assertion + ruff + pytest (151).
<!-- SECTION:NOTES:END -->

