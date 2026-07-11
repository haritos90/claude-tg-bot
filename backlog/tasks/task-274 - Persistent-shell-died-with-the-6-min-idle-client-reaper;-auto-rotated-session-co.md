---
id: TASK-274
title: "Persistent shell died with the 6-min idle client reaper; auto-rotated session could be code"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 274
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Your `/shell` session now stays alive (cd, env, running server intact) for up to a day while you step away or chat with the bot about the output — instead of being killed a few minutes after going idle; and a session that auto-starts after an idle gap is always a plain chat (never a code session).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two changes. (1) The `/shell` jailed shell was torn down whenever the #179 reaper recycled the session's `claude` client (~6 min idle), so a user who stepped away to discuss command output with the bot lost their cd/env + running command. The shell costs ~3 MB (a `bash` + `bwrap` supervisor, measured) vs ~500 MB for the client, so it no longer dies with the client: on reap (or any config-drift rebuild) a live shell is DETACHED into `SessionManager._detached_shells` and re-attached on the next rebuild (`engine.ClaudeSession.has_live_shell/detach_shell/adopt_shell`), keeping cd/env + any running command alive. It gets its own long TTL (`SHELL_TTL_SEC`, default **24h**) aged out by the SAME single reaper (`_reap_once` calls a new `_reap_detached_shells` pass — no separate loop), and is torn down for good on session delete/reset (`_drop_detached_shell`) or shutdown. Measured cost: a hanging shell is ~3 MB (bash + bwrap supervisor) vs ~500 MB for the claude client, so keeping it for hours is negligible. +3 tests (preserve-on-evict→reattach; TTL/death reap; drop-on-reset). (2) An idle auto-rotation (#271) now always starts a CHAT session, never code — code is a heavier, privileged mode entered only on an explicit `/code` or `/new code`, so an automatic rotation must not silently mint one. py_compile + import + ruff clean; suite 219 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

