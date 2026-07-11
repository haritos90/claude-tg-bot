---
id: decision-7
title: "Credential broker keeps the OAuth token outside the jail"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The jail must reach the Anthropic API, but the real OAuth bearer must never sit inside a container the user's code can read.

## Decision

A host sidecar (`deploy/cred-broker.py`) injects the REAL bearer into outbound requests; the jail holds only a `BROKER-PLACEHOLDER`. The broker enforces an inbound method/path allowlist and MUST stream (`read1(n)`, never `read(n)`) so it does not buffer the whole SSE reply.

## Consequences

- Token exfiltration from a compromised session is blocked.
- A broker that buffers silently kills live streaming — the canonical trap: when streaming goes dark, debug UPSTREAM at the broker, not at the draft layer.
- The broker reads the OAuth creds fresh each turn, which also enables proactive token refresh.

**Source tasks:** #119, #228, #193, #194
