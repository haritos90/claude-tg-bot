---
id: decision-8
title: "Global memory is injected into the prompt, never via setting_sources"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The owner's `~/.claude/CLAUDE.md` (+ memory) should optionally reach the model, but widening `setting_sources` to `["user"]` to load it would ALSO load `settings.json` — whose `permissions.allow` could auto-allow withheld tools and whose `env` could merge an API key.

## Decision

Keep `setting_sources=[]` always and INJECT the owner's CLAUDE.md/memory (and any workdir CLAUDE.md) CONTENT directly into the system prompt when the feature is on.

## Consequences

- Memory reaches the model without ever loading `settings.json` — no tool-gate bypass, no billing-flip risk; preserves the isolation invariant.
- Also works under the jail, whose HOME has no `~/.claude`.
- Memory edits take effect on the next rebuild (re-read each build).

**Source tasks:** #130, #122, #314
