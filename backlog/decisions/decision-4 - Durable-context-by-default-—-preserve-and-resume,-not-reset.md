---
id: decision-4
title: "Durable context by default — preserve-and-resume, not reset"
date: '2026-07-04 00:00'
status: accepted
---
## Context

A restart, an idle eviction, or a mid-turn kill must not silently drop the user's context.

## Decision

Context is durable by default. The idle reaper RESUMES the same transcript; a long-idle session rotates to a FRESH one but PRESERVES the old (switchable via `/sessions`), and rotation is per-USER. A turn killed mid-flight keeps its resume id so the next message continues the same session.

## Consequences

- Users never lose history to ops events; old sessions accrue and are archived / GC'd separately.
- 'Start fresh after long idle' is an opt-in INVERSE default, not the norm.
- resume is cwd-keyed, so any workdir move must re-encode the transcript dir (see the session-identity ADR).

**Source tasks:** #54, #179, #261, #266, #329, #324
