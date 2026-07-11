---
id: TASK-130
title: "Global memory: inject CLAUDE.md directly, not setting_sources=[\"user\"]"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 130
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Global memory: inject CLAUDE.md directly, not setting_sources=["user"]
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`setting_sources` is now `[]` UNCONDITIONALLY; global memory injects the owner's ~/.claude/CLAUDE.md (+ memory/*.md) CONTENT into the system prompt instead (`engine._global_memory_block` — chat appends to CHAT_SYSTEM_PROMPT, code uses the claude_code preset `append`). settings.json (permissions/env) is never loaded; also works under the sandbox. Unit-tested (tests/test_engine.py).
<!-- SECTION:NOTES:END -->

