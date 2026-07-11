---
id: TASK-269
title: "Move the agent's self-description into a project doc (agent_context.md) + refresh the /shell message"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 269
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The shell-mode message now describes what shell mode actually does (persistent cd/env, interactive input, detach), and the bot's "who am I / what can I do" knowledge lives in an editable project document — so improving how the bot explains itself no longer needs a code change.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two fixes. (1) The `/shell` toggle-on message (`shell.on`) was stale — it said "non-interactive only; cd/env don't persist yet", but the persistent jailed shell (#227) makes cd/env persist and supports interactive input via the keypad, and the toggle DETACHES (background keeps running). Rewrote it (en + ru) to match. (2) #265's hardcoded `BOT_CONTEXT_NOTE` string was replaced by a maintained PROJECT DOCUMENT, `agent_context.md`, loaded at import by `engine._load_bot_context()` (with a short built-in fallback if the file is missing) and still appended to BOTH system prompts — so the bot's self-description is edited in one human-readable doc, not in code (a restart picks up edits). Expanded the content while there: identity + turn model, the two modes (/code ⇄ /chat), shell mode (/shell — persist, interactive, detach, no TUIs), sessions (isolation, /new, /sessions, /rename, /reset, /fork, auto-name, idle→new), files (attachments in; outbox + /export + /files out), the useful commands to point users at (/model, /effort, /settings, /status, /context, /limits, /stop, /retry, queue-while-busy, /schedule, /secret), and Telegram rendering limits — with a guardrail to only describe real features and guide rather than refuse/fake. Doc is English-only, no provenance. +existing tests still assert the note lands in both modes. py_compile + import + ruff + i18n parity clean; suite 215 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

