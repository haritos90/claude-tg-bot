---
id: TASK-369
title: '`/forget` gates on session MODE only, not the caller LEVEL (demotion gap)'
status: Done
assignee: []
created_date: '2026-07-12 10:17'
updated_date: '2026-07-12 10:37'
labels:
  - security
  - bug
dependencies: []
priority: medium
ordinal: 7362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/forget` (cmd_forget, app/telegram/handlers.py:~2947) rejects only when the SESSION mode is not code — it does not re-check the CALLER's current access level. A user demoted from code to chat, acting on a still-cached code-mode session, can run /forget and wipe the topic's agent-saved session memory (the `remember` notes), which is a code-only feature.

Both sibling commands for the same code-only session-memory feature guard the caller's level:
- cmd_memory (app/telegram/handlers.py:~2911): `state.mode == "code" and _has_code_access(uid, uname)`.
- cmd_shell (~3279) and cmd_files (~3119): the explicit level gate (`if not _has_code_access(...): reject`).

cmd_forget's own comment claims parity with /files and /shell, but the `_has_code_access` check is missing — this is the demotion gap the level check exists to close (gate code features on the user LEVEL, not just the session MODE).

Fix: after the `state.mode != "code"` check in cmd_forget, add the caller-level gate mirroring cmd_shell — `if not _has_code_access(uid, uname): reply(common.code_only / access denial); return`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A demoted (code to chat) caller acting on a cached code-mode session is rejected by /forget.
- [ ] #2 cmd_forget gating matches cmd_memory and cmd_shell (_has_code_access level check).
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. cmd_forget (app/telegram/handlers.py) now runs the caller-level gate right after the session-mode check: `if not _has_code_access(uid, uname): reply(access.code_denied); return`, mirroring cmd_shell / cmd_files / cmd_memory. A user demoted code->chat can no longer wipe session memory on a stale code-mode session. Full suite 279 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
