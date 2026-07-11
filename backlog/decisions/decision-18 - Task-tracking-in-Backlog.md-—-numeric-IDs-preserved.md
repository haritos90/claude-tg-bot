---
id: decision-18
title: "Task tracking in Backlog.md — numeric IDs preserved"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Work was tracked in a hand-maintained `TODO.md` (Backlog->Open->Closed->Deferred tables). It grew to 360 tasks and duplicated a task-manager's job, and its numeric ids are referenced by `#N` in code comments (the comment-out-with-a-task-ref convention).

## Decision

Adopt Backlog.md as the SINGLE source of truth — tasks (and these key-decision ADRs) as plain markdown under `backlog/`, managed with the `backlog` CLI. Migrate all 360 tasks PRESERVING their numeric ids exactly (`task-N` == `#N` in code); gaps are kept, not backfilled; new tasks auto-increment. `TODO.md` is retired.

## Consequences

- Standard tooling (`backlog board` / `search` / web UI); ids stay stable for code auditability, so code comments never go dangling.
- `auto_commit: false` keeps the never-commit rule; each task's resolution lives in its Implementation Notes.
- Two IDs (48, 259) are permanent gaps; never renumber to close them.

**Source tasks:** the task-tracking migration (all 360 tasks)
