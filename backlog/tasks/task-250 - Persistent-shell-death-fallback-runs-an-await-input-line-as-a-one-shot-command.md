---
id: TASK-250
title: "Persistent-shell death fallback runs an await-input line as a one-shot command"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 250
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
If the shell ends while a program is waiting for input, your typed input is discarded instead of being run as a shell command.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
In `sessions._run_shell_command`, the `except` fallback to the #224 one-shot reset `shell_awaiting=False` and ran `run_shell(cmd)`. If the persistent shell died WHILE awaiting input, `cmd` was the user's INPUT (a password, a menu choice) — not a command — and got executed as a standalone shell command. Now, on fallback while `awaiting`, the input is DROPPED with a new `shell.ended` notice (en+ru) instead of being run. py_compile + import + i18n symmetry + ruff clean; suite 167 passed (1 pre-existing PIL font failure); live restart "Run polling".
<!-- SECTION:NOTES:END -->

