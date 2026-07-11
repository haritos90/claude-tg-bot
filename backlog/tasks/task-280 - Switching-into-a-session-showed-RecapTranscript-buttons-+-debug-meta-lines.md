---
id: TASK-280
title: "Switching into a session showed Recap/Transcript buttons + debug meta lines"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 280
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Switching into a session now just confirms "switched to <name>" — no extra Recap/Transcript buttons or technical id/model/usage lines cluttering the chat.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Tapping a session to switch into it opened a card with Recap + Transcript quick buttons and three lines of detail (name, mode tagline, and a sid/model/date/requests/tokens meta line). The buttons duplicate what's in the session options menu / settings, and the meta line is debug noise. Switching now shows ONLY the one-line confirmation (`_session_switch_line` — "switched to <glyph> <name>") with no buttons; the full card (`_session_card`) is unchanged where it's still used (the post-recap re-render). py_compile + import + ruff clean; suite 226 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

