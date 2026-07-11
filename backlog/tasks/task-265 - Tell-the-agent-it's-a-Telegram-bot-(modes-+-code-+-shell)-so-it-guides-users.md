---
id: TASK-265
title: "Tell the agent it's a Telegram bot (modes + /code + /shell) so it guides users"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 265
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot now understands and can explain what it is and what it can do — e.g. in a chat session it tells you to `/code` or `/shell` when you ask it to run something, instead of refusing or pretending.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The model had no idea it was running behind a Telegram bot — so when a chat-mode user asked it to run a command or edit a file, it either refused vaguely or pretended. Added a shared `engine.BOT_CONTEXT_NOTE` appended to BOTH system prompts (chat string + the code `claude_code` preset append, alongside the existing OUTBOX/ISOLATION/TABLE notes): it states the bot identity (Telegram frontend, one message per turn, isolated per-topic sessions that may rotate after idle), the two modes (CHAT = web tools only; CODE = full Claude Code toolset in a sandbox), and the unlock commands (`/code` ⇄ `/chat`, `/shell` for a persistent jailed shell in code) — with a guardrail to only describe features that exist and point the user at the right command instead of refusing/faking. +2 tests (note present in both modes; updated the exact-chat-prompt assertion). py_compile + import + ruff clean; suite 213 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

