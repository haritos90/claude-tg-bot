---
id: TASK-273
title: "Default session names didn't signal a freshly-started, empty session"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 273
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A just-started session (e.g. after an idle gap, or `/new` without a name) is now named "New chat" / "New code session" so it's clear it's fresh and empty until you start talking.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The default names for a session created without one were "Chat session" / "Code session" (and "Session 1" on first contact) — they didn't convey that the session was just started and is empty (auto-title via #260 only appears once it has a conversation). Renamed (en + ru) to "New chat" / "New code session" (first-contact default aligned to "New chat" too); the word "session" is kept only for the code default. Pure i18n; the #260 auto-rename still replaces the default once the session has content. py_compile + i18n parity clean; suite 216 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

