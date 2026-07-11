---
id: TASK-111
title: "Terminal-style code session cards"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 111
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions look terminal-like (a green-square prompt with the working dir).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The code-mode tagline and the `/status` directory line render as a shell prompt — `🟩 …` + `<code>{cwd} $</code>` (`mode.tagline_where` is now a monospace prompt line, `status.directory` → `📂 <code>{cwd} $</code>`); the switch card passes the session's `cwd` into the tagline. Chat sessions keep 💬.
<!-- SECTION:NOTES:END -->

