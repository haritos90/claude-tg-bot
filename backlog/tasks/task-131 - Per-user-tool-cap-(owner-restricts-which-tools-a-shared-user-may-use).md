---
id: TASK-131
title: "Per-user tool cap (owner restricts which tools a shared user may use)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 131
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Owner controls which tools each shared user can use.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`allowlist` `tool_cap` (list = allowed tools, None = uncapped) + `tool_cap_of`/`set_tool_cap`; `sessions._resolve_tool_cap` → `engine._resolve_tools` intersects the session's enabled tools with the cap (owner always uncapped). Set from the `/users` card → 🧰 Tools sub-page (toggle each tool; applies to all the user's sessions). Audit-driven follow-up to the #121 batch.
<!-- SECTION:NOTES:END -->

