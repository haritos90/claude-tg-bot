---
id: TASK-231
title: "Sandbox is mandatory for all sessions; retire the per-session toggle; alert only on real uid collisions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 231
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The sandbox is now always on for every session (chat and code) and can't be turned off — the per-session toggle and `/sandbox` command are gone. The startup isolation check no longer pings the owner for the harmless just-migrated state, only for a real per-session uid clash.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The bubblewrap jail already covered BOTH chat and code (`_build_options` calls `_enable_sandbox` for any session with `sandbox` on; per-session uid + seccomp + broker apply to all modes, egress + cgroup limits to code only) — but a per-session opt-out (`no_sandbox`, set via `/sandbox` + the `/settings` Sandbox row) and a debug toggle still existed. Made the sandbox MANDATORY with no exceptions: removed the `sandbox` row from `PAGE_ORDER` (gone from every `/settings` scope), retired the `/sandbox` command (`commands.py` entry + `cmd_sandbox` now a no-op that replies `sandbox.mandatory`; old toggle logic kept commented), so `no_sandbox` is never set again (all live sessions already had it 0). The `sandbox` Setting + adapters stay (drive resolution) and `SANDBOX_CODE` stays the deployer kill-switch. Also fixed the #221 uid-doctor to alert only on a GENUINE break: `_uid_collisions` now EXCLUDES uid 0 (root) — root ownership is the routine pre-first-turn / no-jail default (a workdir is root-owned until a session's first turn chowns it to its claimed per-session uid; it never indicates the birthday-collision the doctor catches, two sessions sharing the same ASSIGNED non-root uid), so a benign warning no longer fired the owner on every restart. Docs updated (CLAUDE.md, isolation.md) to state the jail is mandatory for all sessions. py_compile + import + doctor/i18n/PAGE_ORDER checks; live, doctor logs clean, polling.
<!-- SECTION:NOTES:END -->

