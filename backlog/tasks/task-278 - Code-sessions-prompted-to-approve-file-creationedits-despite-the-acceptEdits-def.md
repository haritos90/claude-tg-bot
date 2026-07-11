---
id: TASK-278
title: "Code sessions prompted to approve file creation/edits despite the acceptEdits default"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - bug
dependencies: []
ordinal: 278
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Creating or editing files in a code session no longer asks for approval every time — the default "auto-edits" now actually auto-accepts file edits (only risky push/destructive/web actions still prompt), matching how it was meant to work since the sandbox became the safety layer.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A code session stored `permission_mode='default'` — the pre-#212 "ask for EVERY tool" policy — because both insert paths (`db._ensure_state`, `db.allocate_dm_session`) and the column default hardcoded `'default'`, and the effective-settings `… or "acceptEdits"` guard only caught NULL/empty, not the literal string. Since #212 dropped `'default'` from the permission picker (the choices are acceptEdits / plan / full-access; the #119 jail is the containment layer), a stored `'default'` could only be stale — yet it made Write/Edit (and ordinary Bash) prompt every time. Fixed at three layers: the two INSERTs + the column default + the COALESCE fallback + the `ThreadState` default now use `'acceptEdits'`; a one-time data migration rewrites existing `permission_mode IN ('default', NULL)` rows to `'acceptEdits'`; and `sessions._coerce_perm` maps any lingering `'default'` to `'acceptEdits'` in both the effective and raw settings paths (belt-and-suspenders for the live gate). +2 tests (legacy-row migration; the existing migrate-defaults assertion updated). Verified on the live DB: all code sessions flipped `'default'`→`'acceptEdits'` on restart. py_compile + import + ruff clean; suite 224 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

