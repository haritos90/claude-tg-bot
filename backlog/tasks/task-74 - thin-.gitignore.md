---
id: TASK-74
title: "thin `.gitignore`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - build
dependencies: []
ordinal: 74
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
thin `.gitignore`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Expanded to a full Python block (`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`.coverage`/`htmlcov`/`.tox`/`.eggs`/`*.egg`), cross-platform OS + editor sections, and `.env` + `.env.*` with `!.env.example`; kept `CLAUDE.md`/`.claude/` + secret/runtime entries.
<!-- SECTION:NOTES:END -->

