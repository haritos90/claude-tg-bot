---
id: TASK-276
title: "The agent didn't know the user's access level or the live session mode"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 276
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot now knows whether you're a chat-only or code user and whether the current session is chat or code, so it explains your options correctly — e.g. it won't tell a chat-only user to "/code" (which they can't do), and tells a code user how to upgrade the session.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The model had only the static "two modes" doc, so it couldn't tailor guidance to THIS user. Added a dynamic, per-session "This session right now" note (`engine.ClaudeSession._session_state_note`, appended to BOTH system prompts) computed from the session mode + the owner's access level (`sessions._owner_level` → new `user_level` ctor arg): a code session → "you have the full toolset + /shell, /chat to go back"; a chat session where the user HAS code access → "tell them to /code (then /shell), /chat to switch back"; a chat session for a chat-ONLY user → "they cannot self-upgrade — only the owner can grant code access; don't tell them to /code". So the agent gives an accurate mini-guide instead of guessing or pointing a chat-only user at a command they can't use. +test (all three mode/level combinations) + updated the exact-prompt assertion. py_compile + import + ruff + i18n parity clean; suite 220 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

