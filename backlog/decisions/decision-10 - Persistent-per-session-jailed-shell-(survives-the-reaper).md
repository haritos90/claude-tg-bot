---
id: decision-10
title: "Persistent per-session jailed shell (survives the reaper)"
date: '2026-07-04 00:00'
status: accepted
---
## Context

A one-shot jailed runner could not hold cd/env or drive line-interactive flows (`gh auth login`, REPLs, `read`).

## Decision

`/shell` (code sessions) holds ONE long-lived `bash -i` per session on a host-driven PTY, so cd/env persist and an interactive prompt gets an inline keypad. Toggling `/shell` DETACHES (tmux-style): the shell and any running command survive in the background. The shell (~3 MB) SURVIVES the client reaper with its own long TTL.

## Consequences

- Real interactive workflows run inside the jail; cd/env persist while you step away.
- Full-screen TUIs (`vim`/`top`) are refused (can't render in a bubble); Ctrl-C is best-effort (no controlling tty).
- A stuck command is reaped on idle or session delete.

**Source tasks:** #224, #227, #246, #274
