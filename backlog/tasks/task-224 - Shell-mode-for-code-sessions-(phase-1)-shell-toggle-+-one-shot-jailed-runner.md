---
id: TASK-224
title: "Shell mode for code sessions (phase 1): `/shell` toggle + one-shot jailed runner"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 224
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions can toggle `/shell` to run shell commands straight in their sandbox — no AI, no tokens (e.g. git/gh with a `/secret` token). Each command runs one-shot (no `cd`/env persistence yet); a `[shell]` tag marks the session.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A `/shell` single-toggle overlay on code sessions (`threads.shell_mode`, mirrored on the live `_ThreadRecord`; does NOT change the session type — stays `code`). When on, the catch-all routes each message to `engine.ClaudeSession.run_shell` — a ONE-SHOT `bash -lc` in the session's #119 jail (per-session uid + egress + seccomp + injected `/secret` env, no LLM, no tokens) via a new `SBX_MODE=shell` branch in `deploy/sandbox-claude.sh`; output posts as a code block (60k cap + truncate). A `[shell]` marker shows in the status / session-card / options headers; a not-found command (exit 127) appends a one-line "you're in shell mode — /shell to exit" hint. Code-only gated; routing-only flag (no session rebuild). Verified: jailed exec runs as the per-session host uid with the workdir chowned correctly (direct launcher test, both uid paths), shell_mode db roundtrip, pytest (155), ruff, `bash -n`; live on the bot. Persistent `cd`/env + interactivity + Ctrl-C + idle-reaper/RAM caps deferred to #227.
<!-- SECTION:NOTES:END -->

