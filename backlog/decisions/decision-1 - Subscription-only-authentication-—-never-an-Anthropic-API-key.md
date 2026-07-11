---
id: decision-1
title: "Subscription-only authentication — never an Anthropic API key"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The bot runs Claude through the owner's Pro/Max subscription via the Agent SDK / `claude` CLI. Setting `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) ANYWHERE — machine, `.env`, systemd, a spawned env, a test harness — silently flips the whole deployment to paid per-token billing.

## Decision

Never set or read an Anthropic API key. Auth is exclusively the OAuth credentials from `claude setup-token` (`~/.claude/.credentials.json`). API-key-only SDK features (custom `betas`, `max_budget_usd`) are treated as no-ops and avoided; the 1M window is requested via a model-id suffix instead (see the 1M-context ADR).

## Consequences

- Zero per-token cost; bounded instead by the subscription's rolling 5h / 7d limits.
- Every code path (env build, sandbox, credential broker, tests) is audited to keep the key out — this is the #1 P0 hard rule.
- A leaked key is the single highest-impact failure, so the credential broker keeps even the OAuth bearer out of the jail.

**Source tasks:** #2, #119, #134
