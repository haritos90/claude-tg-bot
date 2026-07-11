---
id: decision-13
title: "Session identity: stored ULID public id + ULID-named workdirs"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Early ids were a position or a 24-bit 6-hex sid, which could collide and leaked internal numbering; the display id was coupled to storage.

## Decision

Each session has a stored ULID public id (decoupled, display-only) and its on-disk workdir is named by that ULID (collision-safe). Because `resume` is keyed by cwd, a workdir rename re-encodes the transcript dir and re-keys the session uid.

## Consequences

- No id collisions; internal numbering never leaks to the user.
- A cwd change MUST re-encode the transcript dir or `resume` breaks (a known trap) — migrations off the old sid did exactly this.
- The public id is display-only; internal joins use the stable thread id.

**Source tasks:** #327, #332, #140, #97
