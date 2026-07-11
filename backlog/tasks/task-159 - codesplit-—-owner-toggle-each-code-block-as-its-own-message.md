---
id: TASK-159
title: "/codesplit — owner toggle: each code block as its own message"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 159
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Owner can switch code blocks between separate messages (easy mobile copy) and inline.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Telegram mobile lacks a per-code-block copy button (desktop has one); the workaround of sending each fenced block as its OWN message is now a persisted global toggle. `streamer.finish` picks `_render_message_chunks` (split — default) vs `_render_chunks` (inline) from `SessionManager.split_code_messages`; `/codesplit on/off` (owner; inline picker; persisted in kv; next-reply effect) flips it; registered in commands.py + i18n + documented in menu.md (§3.7 + §4.5 matrix). Driven by the owner's on-device copy test (short blockquote copies whole on tap; long/expandable only expands; code copies only the tapped word on mobile).
<!-- SECTION:NOTES:END -->

