---
id: TASK-324
title: "A turn killed mid-flight lost its resume id → next message started a fresh session with no context"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 324
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
If the bot is restarted or crashes while it is mid-reply, your session no longer forgets everything — the next message picks the conversation back up instead of starting blank.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Diagnosed from a live incident (an SVG turn): a service restart (exit -15 / SIGTERM) killed the `claude` subprocess mid-generation, so (a) the `<svg>` never closed its fence → it was not rasterized to PNG (sent as truncated raw XML) and (b) the turn never reached its terminal `ResultMessage`, so the session id was never persisted — the NEXT message had no resume id and started a brand-new session with no memory. Root fix: the engine now captures + emits the session id the MOMENT any message carries it (the init message), not only at the terminal result (`engine` yields a `kind="session"` event on first sight; `sessions` has a `session` branch that persists it via `set_chat_session` / `set_code_session` immediately). So a turn killed by a restart / crash / reap still leaves a resumable id and keeps its context. +test (the session event persists the id before the terminal result). compile + import + ruff + suite 238 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

