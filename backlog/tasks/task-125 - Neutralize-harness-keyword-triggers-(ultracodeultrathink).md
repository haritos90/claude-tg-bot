---
id: TASK-125
title: "Neutralize harness keyword triggers (ultracode/ultrathink)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 125
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
ultracode/ultrathink can't burn the subscription.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The bundled CLI acts on `ultracode` (→ multi-agent Workflow) and `ultrathink` (→ effort) keywords. The engine sets `CLAUDE_CODE_DISABLE_WORKFLOWS=1` AND splits the keyword with a space in every prompt (`defuse_triggers`); list = `DEFAULT_KEYWORD_TRIGGERS` + `BLOCKED_PROMPT_KEYWORDS` (env).
<!-- SECTION:NOTES:END -->

