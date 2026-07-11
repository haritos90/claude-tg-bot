---
id: TASK-268
title: "Raise the default per-user session limit 10 → 500"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 268
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
You can now keep up to 500 sessions (was 10) — each costs only its small conversation transcript on disk, so there's plenty of room for many parallel topics and the auto-new-session-on-idle behavior.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A session's on-disk footprint (excluding the user's own files) is just its transcript JSONL — a few KB empty, up to ~1 MB for a very long conversation — and the `claude` CLI is staged ONCE at a shared path, not copied per session. So 10 was needlessly tight, especially now that idle gaps mint new sessions (#266). Raised the default to 500 (`config.Settings.max_sessions_default` + the `MAX_SESSIONS_PER_USER` env default + the handler's defensive fallback). Still overridable: `MAX_SESSIONS_PER_USER` env, the runtime Admin picker (kv `max_sessions_default`), and per-user caps; `0` = unlimited. No KV/`.env` override was set, so the new default is live. py_compile + import + ruff clean; suite 215 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

