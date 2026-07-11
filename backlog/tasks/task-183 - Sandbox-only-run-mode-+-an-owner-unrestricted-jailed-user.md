---
id: TASK-183
title: "Sandbox-only run mode + an owner \"unrestricted\" jailed user"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 183
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
No change — the owner runs in the same per-session non-root jail as everyone; no special un-sandboxed path exists.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Resolved — no code change needed. Part 1 (sandbox-only, no on/off) shipped in #231 (the jail is mandatory for every session, owner included; the `/sandbox` toggle + `no_sandbox` were retired). Part 2 (an "unrestricted" owner profile replacing a root-on-host fallback) is moot: `deploy/sandbox-claude.sh` runs EVERY session under `--unshare-user` + a per-session non-root host uid (#119, `SANDBOX_PER_SESSION_UID`) with no owner branch — there is no root-on-host path left to replace, and the owner is already a jailed non-root uid like everyone. Deliberately NOT relaxing the jail (egress/seccomp/caps) for the owner — the per-session-uid sandbox contains all sessions safely as-is. Full-access (bypassPermissions) is already delegated to code users and sandbox-contained (#223); the lone `is_owner` line in the permission soft-revoke is correct logic, not a privilege.
<!-- SECTION:NOTES:END -->

