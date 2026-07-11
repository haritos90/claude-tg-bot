---
id: TASK-227
title: "Shell mode phase 2: persistent PTY shell + interactivity + lifecycle"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 227
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The jailed shell is now persistent and interactive: `cd`/env survive between messages, prompts (incl. arrow-key pickers) are driven by an on-screen key keypad, and `/shell` detaches so a long command / server keeps running while the agent continues.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A held login `bash -i` per code session on a host-driven PTY (`engine.PersistentShell`; launcher branch `SBX_MODE=shell_persist`), reusing the #119 jail. (227a) `shell_run` writes `cmd; printf <sentinel>:$?` as ONE line and reads the master until the sentinel → `(rc, output)`; `stty -echo`/`PS1=` + `_TERM_NOISE_RE` (CSI/OSC + two-char ESC like ESC 7/8) give clean output; cd/env persist. (227b) `_drive` returns `done`/`awaiting`(settle after output)/`timeout`; a paused command flips the session to await-input and the next message is forwarded as input/keys. Telegram-native UX: `_run_shell_command` attaches an inline KEYPAD (Esc ↑ Enter / ← ↓ → / Tab ^C ⋯more; `shell_keypad` + `handlers.on_shell_key` callback edits the message in place via `shell_key`→`shell_send_keys`); `streamer.finish`/`_commit` gained `reply_markup`. Typed key fallback `.up`/`.down`/`.enter` (prefix `.`, not `:`). #245 relaxed → only full-screen TUIs refused (`_is_fullscreen_tui_cmd`). (227c) `/shell` toggle = DETACH (shell + running command stay alive in the background, agent resumes; re-attach keeps cd/env + await state); torn down on session delete/evict (`aclose` `_close_shell`) + #179 idle reaper; cgroup mem/pids caps apply via the jail. Local PTY tests confirm cd/env persistence, rc, clean output, and the chained prompt→input→prompt→input flow; +tests (parse, keypad, key-tokens, TUI guard). py_compile + ruff + suite (167) clean; live restart "Run polling"; keypad confirmed on-device. CAVEATS (→ #246): Ctrl-C is the `\x03` byte (no controlling tty → not a true SIGINT, so a hung command is reaped on idle / killed on delete); a full-redraw arrow picker streams as snapshots. For GitHub auth prefer a token over the browser flow.
<!-- SECTION:NOTES:END -->

