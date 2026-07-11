---
id: TASK-170
title: "Native rich lists / checklists in our own (read-only) UI"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 170
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/status` is now a clean native checklist; the pattern is ready for other read-only screens.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `handlers.reply_rich_html` (sends `sendRichMessage` html, falls back to classic `reply()`); `/status` now renders as a native `<h3>` heading + a `<ul>` **checkbox list** for session flags (checkbox = on/off — display-only, so the interactive menus correctly stay inline-keyboard). Reusable primitive for `/help` / session cards next.
<!-- SECTION:NOTES:END -->

