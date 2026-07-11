---
id: TASK-88
title: "no committed linter/test config"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - build
dependencies: []
ordinal: 88
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
no committed linter/test config
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `pyproject.toml`: `[tool.ruff]` (line-length 100, py311, lean green rule set E4/E7/E9/F/W/B) + `[tool.pytest.ini_options]` so local `ruff`/`pytest` match CI. `ruff check .` clean.
<!-- SECTION:NOTES:END -->

