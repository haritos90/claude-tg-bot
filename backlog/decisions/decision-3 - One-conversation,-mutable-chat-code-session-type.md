---
id: decision-3
title: "One conversation, mutable chat<->code session type"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Early design bound a session's mode at creation (chat XOR code). Users wanted to start a lightweight chat and later escalate to code (or step back) without losing the conversation.

## Decision

A session's type is MUTABLE. It starts as chat (tool-free) and upgrades to code (`/code`) or downgrades (`/chat`), carrying the SAME transcript and cwd (chat and code resume the same session). Escalation to code is gated by the user's access level.

## Consequences

- One continuous conversation across modes; the workdir is shared (chat uses it only for transcript storage).
- Chat ships only the read-only web tools; code adds the full toolset plus egress allowlist + DoS caps.
- Mode is a per-session setting that a rebuild must honor without tearing the transcript.

**Source tasks:** #53, #133
