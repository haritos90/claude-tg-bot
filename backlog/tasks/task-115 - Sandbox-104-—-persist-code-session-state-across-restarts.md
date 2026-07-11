---
id: TASK-115
title: "Sandbox #104 — persist code-session state across restarts"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 115
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sandboxed code sessions keep their context across restarts.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The bubblewrap jail's HOME is a private tmpfs, but `~/.claude/projects` is now bind-mounted from a per-session host dir (`BASE_WORKDIR/<key>.sbxstate`, passed as `SBX_STATE`, created in `engine._ensure_client`, removed on session delete) so claude's `resume` survives a client rebuild / bot restart. Verified end-to-end: a brand-new sandboxed client resumed a prior session and recalled the planted word. The credential overlay stays ephemeral.
<!-- SECTION:NOTES:END -->

