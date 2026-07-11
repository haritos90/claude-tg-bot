---
id: TASK-24
title: "chat mode was not tool-free (model used WebSearch in chat)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 24
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
chat mode was not tool-free (model used WebSearch in chat)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Set `tools=[]` for chat (not `None`); `None` left the CLI default tools on. See AGENTS.md §5
<!-- SECTION:NOTES:END -->

