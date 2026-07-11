---
id: TASK-245
title: "One-shot shell hangs the session on an interactive command (e.g. `gh auth login`)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 245
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Interactive shell commands (like `gh auth login`) no longer freeze the session for a minute — the bot replies immediately that the one-shot shell can't take interactive input and suggests a non-interactive alternative.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Shell phase 1 (#224) runs `bash -lc` with `stdin=/dev/null` + a 60s timeout, so an interactive command (gh auth login device-flow, editors, REPLs, ssh, sudo) can't read input and HUNG the session's worker for the full 60s — every other message queued (#236) and the bot looked dead until the timeout killed it (the reported case). Added `sessions._is_interactive_shell_cmd` (heuristic on the first command word + REPLs + a few phrases like `gh auth login` / `git rebase -i` / `sudo` without `-n`); `_run_shell_command` now refuses such commands INSTANTLY with the new `shell.interactive` hint (suggesting a non-interactive form, e.g. `gh auth login --with-token`) instead of running them. True interactivity remains #227 (persistent shell). +test `test_is_interactive_shell_cmd`. py_compile + import + ruff + suite (164) + i18n round-trip clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

