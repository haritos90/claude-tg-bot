---
id: decision-14
title: "1M context via the [1m] model-id suffix, not the betas param"
date: '2026-07-04 00:00'
status: accepted
---
## Context

A 1M-context window was wanted for big sessions, but the SDK `betas=["context-1m-..."]` param is API-key-only ('Custom betas are only available for API key users') — a silent no-op under the subscription.

## Decision

Request the 1M window by appending the `[1m]` suffix to the model id (for 1M-capable models — Opus by default), NOT via the `betas` param.

## Consequences

- 1M works under the subscription auth.
- Code mode runs 1M by default; chat opts in via `/memory` (the '1M context' toggle).
- The dead `betas` branch is kept commented for history/revert.

**Source tasks:** #134
