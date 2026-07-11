---
id: TASK-281
title: "A chat-level user was shown the \"New code\" button (could see a code-create option)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - bug
dependencies: []
ordinal: 281
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A chat-only user no longer sees a "New code" button they aren't allowed to use — the option is hidden, not just blocked on tap.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `/sessions` browser rendered both "New chat" and "New code" create buttons unconditionally, so a chat-only user SAW the "New code" option (a permissions-surface leak) even though the `ses:new:code` handler correctly denied the tap. `_render_sessions` now offers "New code" ONLY when the DM user has code access (owner, or a code grant — checked by numeric id, which is authoritative); a chat-only user sees just "New chat". The handler-side gate (and `/newcode` → `_do_new`'s `can_code` check) stay as defense-in-depth. py_compile + import + ruff clean; suite 226 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

