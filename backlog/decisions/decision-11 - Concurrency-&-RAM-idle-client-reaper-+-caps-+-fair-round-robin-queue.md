---
id: decision-11
title: "Concurrency & RAM: idle client reaper + caps + fair round-robin queue"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Each `claude` client is ~500 MB; unbounded concurrent sessions OOM a small box, and one busy user could starve others.

## Decision

An idle reaper evicts idle clients (freeing RAM; the transcript resumes on next use) under a concurrency cap; a fair cross-session turn queue round-robins by USER so nobody starves. A soft restart DRAINS in-flight turns instead of killing them.

## Consequences

- Bounded memory on a small VPS; fairness under parallel load; no torn transcripts on restart.
- The reaper frees the heavy client but DETACHES the light jailed shell so cd/env survive; one reaper handles both client eviction and shell aging.
- Eviction adds first-token latency after idle (an accepted trade).

**Source tasks:** #179, #326, #325, #274
