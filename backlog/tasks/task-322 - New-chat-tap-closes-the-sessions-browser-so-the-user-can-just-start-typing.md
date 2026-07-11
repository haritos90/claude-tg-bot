---
id: TASK-322
title: "New-chat tap closes the sessions browser so the user can just start typing"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 322
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Pressing "New chat" now clears the session list out of the way so you can immediately start writing — instead of leaving the list and buttons on screen.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Tapping "➕ New chat" in the `/sessions` browser used to create the session and RE-RENDER the list (leaving the browser + buttons on screen). Now it DISMISSES the browser entirely (deletes the message, like the Close button) — the new empty session is already current, so the user just types their question. Collapses any stray empty/untitled sessions first (the #307 cleanup the re-render used to do), clears the browser's search state, and shows a toast nudging "just type your question" (`sessions.new_chat_toast`). compile + import + ruff + suite 236 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

