---
id: TASK-282
title: "The \"New chat\" create button and a fresh session's name were identical"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 282
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "➕ New chat" button and a brand-new empty session ("Untitled") are no longer confusable, and a fresh session clearly reads as not-yet-named.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A freshly-created empty session was named "New chat" (#273), the same as the "New chat" create button in the `/sessions` browser — so the action and a session label read identically. Now the create buttons are prefixed "➕" ("➕ New chat" / "➕ New code", dropping the mode glyph) so they read as CREATE actions, and an unused session's placeholder name is "Untitled" (the mode glyph 💬/🟩 conveys chat-vs-code; #260 still auto-names it once it has a conversation). py_compile + i18n parity clean; suite 226 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

