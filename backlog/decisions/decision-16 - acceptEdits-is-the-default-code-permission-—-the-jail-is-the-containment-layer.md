---
id: decision-16
title: "acceptEdits is the default code permission — the jail is the containment layer"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Prompting for approval on every file edit was noise once the bubblewrap jail became the hard containment layer.

## Decision

Default code `permission_mode` is `acceptEdits` (auto-apply edits, still ASK for dangerous ops), because containment is enforced by the JAIL, not by per-edit prompts. A Bash denylist still blocks recursive-delete and alternate command forms; a soft-revoked full-access reverts to asking.

## Consequences

- Far fewer prompts in code sessions; safety comes from the jail + egress/DoS caps.
- Dangerous tools are still gated by the `can_use_tool` callback per call.
- The security story now depends on the sandbox being mandatory (see that ADR) — the two decisions are coupled.

**Source tasks:** #212, #278, #219
