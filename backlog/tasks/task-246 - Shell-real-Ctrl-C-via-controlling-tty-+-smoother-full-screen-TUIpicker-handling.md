---
id: TASK-246
title: "Shell: real Ctrl-C via controlling-tty + smoother full-screen TUI/picker handling"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 246
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ctrl-C now really interrupts a stuck shell command, and a full-screen picker shows its current screen instead of a pile of redraw snapshots.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two #227 on-device follow-ups. **246a — real Ctrl-C**: `engine._start_shell` gives the jailed bash a CONTROLLING TTY via `os.login_tty(slave)` in `preexec_fn` (+ `pass_fds=(slave,)`), replacing `start_new_session=True` (login_tty's setsid keeps it a session leader, so the #179 reaper/cgroup invariant is unchanged); bwrap is not `--new-session`, so the tty persists through setpriv→bwrap→bash even across `--unshare-pid`. The 0x03 byte is now a REAL SIGINT to the foreground group — a hung command (polling `gh auth login`) is actually interrupted. Validated e2e (sync / bwrap `--unshare-pid --dev /dev` / asyncio → RC=130). **246b — full-redraw TUI**: `engine._latest_frame` collapses an ALT-SCREEN TUI (sets `ESC[?1049h`) to its latest frame (split on screen-clear / cursor-home / alt-screen toggle, keep the last visible segment), wired into `_clean`/`_parse`; GATED on the alt-screen marker so ordinary output — even a bare `clear` — is untouched. +unit tests (`_latest_frame`, `add_reasoning` analog). py_compile + import + ruff clean; **suite 179 passed**; live restart "Run polling". On-device `/shell` ^C + picker confirmation pending.
<!-- SECTION:NOTES:END -->

