---
id: decision-2
title: "Hard per-session isolation via setting_sources=[]"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Each Telegram topic / DM is an independent session; context, cache, memory, cwd, and session-id must never bleed across topics. In this SDK `setting_sources=None` loads ALL filesystem settings (user/project/local CLAUDE.md + settings.json); `[]` loads none.

## Decision

Pass `setting_sources=[]` on EVERY `ClaudeAgentOptions`, always. Anything the model legitimately needs (owner memory, project instructions) is INJECTED into the system prompt instead of loaded via settings.

## Consequences

- No cross-session context/cache/memory/cwd bleed — the #2 isolation invariant, guarded by a standing test.
- No accidental load of a `settings.json` whose `permissions.allow` could auto-allow a withheld tool or whose `env` could merge an API key.
- Features that would otherwise rely on settings (global memory, workdir CLAUDE.md) are re-implemented as explicit prompt injection.

**Source tasks:** #2, #130, #122
