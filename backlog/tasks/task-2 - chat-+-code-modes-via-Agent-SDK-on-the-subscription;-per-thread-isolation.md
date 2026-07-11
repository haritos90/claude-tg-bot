---
id: TASK-2
title: "chat + code modes via Agent SDK on the subscription; per-thread isolation"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 2
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
chat + code modes via Agent SDK on the subscription; per-thread isolation
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Delivered in `engine.py`: `ClaudeSession`, `setting_sources=[]`, API-key-stripped child env, own cwd + `resume`; verified subscription-only (no API key).
<!-- SECTION:NOTES:END -->

