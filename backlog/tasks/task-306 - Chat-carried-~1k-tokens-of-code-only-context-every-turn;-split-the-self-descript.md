---
id: TASK-306
title: "Chat carried ~1k tokens of code-only context every turn; split the self-description"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 306
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Chat sessions are leaner — they no longer carry code-only instructions — cutting per-message context use; no user-facing behavior change.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`agent_context.md` (appended to BOTH modes) was ~41% code-only content (shell-mode runbook, outbox file-delivery, sandbox/privacy, `/secret`) that a chat session can never use — ~990 tokens of dead weight per chat turn. Split it into a SHARED CORE (`agent_context.md` — what the bot is, modes, sessions, history, commands, rendering) appended to both modes, and a CODE-ONLY ADDENDUM (`code_addendum.md` — shell, file delivery, sandbox/privacy, `/secret`) appended to the code prompt only (`engine._load_code_addendum` / `CODE_ADDENDUM_NOTE`, with a built-in fallback if the file is missing). Also deduped the math guidance (previously in the chat prompt AND the shared doc) by enriching the shared copy and commenting out the chat one. Chat's static system prompt dropped from ~2834 to ~1757 tokens (−38%, ~1077 tok/turn); code keeps full parity (core 1447 + addendum 1098 tok). compile + import + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

