---
id: TASK-279
title: "Shell detach left a stale keypad; re-attach didn't restore a paused interactive prompt"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 279
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Leaving and re-entering `/shell` while a command is waiting for your input now just works: the old keypad disappears when you leave, coming back re-shows the current prompt with its keypad, and your next answer is actually delivered to the command (instead of looking ignored).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Toggling `/shell` OFF while a command was waiting for input (e.g. `gh auth login`'s account picker) left the inline keypad attached to that message — tapping it after returning to the agent did nothing — and toggling `/shell` ON again did NOT bring the keypad back, so the user had to restart the interactive flow from scratch. The session now tracks the live keypad message + its rendered body (`_ThreadRecord.shell_kb_chat/msg/shell_last_render`, set on every awaiting render in `_run_shell_command` and the keypad callback). On detach `cmd_shell` strips the keypad from that message (`EditRichMessage … reply_markup=None`) and forgets the ref while KEEPING the paused render + `shell_awaiting`; on re-attach, if a command is still awaiting input, it re-sends the paused prompt with a fresh keypad (`sessions.shell_kb_ref` / `shell_resume_render` / `set_shell_kb`), so the user continues exactly where input paused. A completed command clears the tracking (no stale restore). Follow-up: forwarded input after a detach/agent-turn round-trip could look IGNORED because `_drive` returned stale buffered output (a prompt the program printed while we weren't reading) instead of the program's response to the new keystroke — `PersistentShell.send_raw` now drains pending output before forwarding input (matching `run()`), and `/shell` re-attach calls a new non-intrusive `shell_peek`/`shell_refresh` to surface any prompt the program advanced to while detached. +tests. py_compile + import + ruff clean; suite 225 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

