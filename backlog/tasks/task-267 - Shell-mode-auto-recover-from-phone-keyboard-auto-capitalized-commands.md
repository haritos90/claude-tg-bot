---
id: TASK-267
title: "Shell mode: auto-recover from phone-keyboard auto-capitalized commands"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 267
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Shell mode now just works when your phone capitalizes the first letter — `Ls` / `Cat file` run as `ls` / `cat file` instead of "command not found"; your filenames and arguments keep their exact case.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A phone keyboard auto-capitalizes the first word, so a user typing `ls` / `cat x` sends `Ls` / `Cat x` and bash returns "command not found" (127). `_run_shell_command` now retries ONCE with `_normalize_shell_cmd` — the command's first TOKEN lowercased (`Ls`→`ls`, `Cat shell.md`→`cat shell.md`, `Python3 app.py`→`python3 app.py`) — but ONLY after the original returns 127. Because nothing runs on a 127, a real command is never altered and a case-sensitive name can't be confused; and only the command WORD is touched, so arguments/paths/filenames keep their case (`Cat Notes.md`→`cat Notes.md`). Applied to both the persistent (`shell_run`) and one-shot (`run_shell`) paths; input-forwarding (await-input) is untouched. +3 tests (normalizer cases; retry-on-127 shows real output; no second run when found). py_compile + import + ruff clean; suite 215 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

