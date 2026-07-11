---
id: TASK-139
title: "Single source of truth for command names (commands.py registry)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 139
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Command names can't drift across languages or surfaces again.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `commands.py`: frozen `Cmd(slug, aliases, scope[all/code/owner], in_menu, label{en,ru}, help_group)` + `COMMANDS` tuple — the ONE place command names/descriptions live. `handlers` now DERIVES `_COMMAND_NAMES`/`_CODE_`/`_OWNER_` + `_build_commands()` from it (old literal arrays + the `cmd.*` i18n block commented out, #139). Startup `assert_commands_consistent()` scans live `@router Command(...)` decorators and fails loudly on drift (handler↔registry parity, both locales present). Fixed concrete mismatches: stale `/stop` + `/stream` removed from menu+help (handlers commented out); `/stop` typed-refs in /help + queue.cleared now point to the Stop button; `cmd.new` en/ru reconciled; dead `cmd.cwd/dirs/reset` dropped. Owner-menu order preserved (sandbox last).
<!-- SECTION:NOTES:END -->

