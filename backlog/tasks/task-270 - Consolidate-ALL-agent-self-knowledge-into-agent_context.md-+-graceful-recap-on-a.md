---
id: TASK-270
title: "Consolidate ALL agent self-knowledge into agent_context.md + graceful /recap on an empty session"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 270
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot's whole "who am I / what can I do" knowledge now lives in one editable document, and asking /recap right after a fresh (idle-started) session gives a helpful "your earlier chat is under /sessions" instead of a confused "we've never talked".
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two parts. (1) Folded the three remaining hardcoded prompt strings — the outbox file-delivery instructions (#187), the per-session isolation/privacy note (#205/#208), and the table-format note (#243) — INTO the single `agent_context.md` document, so the agent's entire self-description lives in one editable place; the `OUTBOX_INSTRUCTION`/`ISOLATION_NOTE`/`TABLE_FORMAT_NOTE` constants were removed and both system-prompt appends now use just `BOT_CONTEXT_NOTE` (the doc). Added a "Conversation history & memory" section telling the agent: each session has its own history (/last, /recap, /history); an idle gap auto-starts a fresh session, so an empty session is expected — don't answer with bare amnesia or recite long-term memory notes as if they were the conversation; point the user at /sessions to find the earlier one. (2) `cmd_recap` no longer burns a model turn on a session with no logged messages — it replies with `recap.empty_session` (explains the fresh-session behavior + points at /sessions), and otherwise recaps the CURRENT session WITHOUT triggering idle rotation (`_submit` gained an explicit `key` param so /recap targets this session instead of rotating to a new one). Fixes the reported "we've never talked / here's a memory note" reply to /recap after an idle rotation. +tests (consolidated notes present in the code prompt; exact chat-prompt assertion updated). py_compile + import + ruff + i18n parity clean; suite 215 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

