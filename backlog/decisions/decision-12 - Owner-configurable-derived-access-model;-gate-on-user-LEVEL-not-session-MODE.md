---
id: decision-12
title: "Owner-configurable derived access model; gate on user LEVEL not session MODE"
date: '2026-07-04 00:00'
status: accepted
---
## Context

A shared bot needs per-user capabilities (who may use code, expensive effort, which tools) WITHOUT code changes, and demoting a user must actually revoke access.

## Decision

A derived, owner-configurable access model with three levels (owner/code/chat) and per-user overrides, driven by a unified settings schema (registry + resolver + 3-tier scopes). Code-only features gate on the user's LEVEL, not just the session's MODE, closing the demotion gap. Controls are HIDDEN from users who lack them, not merely blocked on tap.

## Consequences

- The owner tunes access at runtime from the `/users` card; access is time-limitable (expiry) and quota-limitable.
- A user demoted code->chat loses code features even on a leftover code session.
- Every new code feature must remember to gate on level, not just mode.

**Source tasks:** #151, #161, #138, #283, #102, #103
