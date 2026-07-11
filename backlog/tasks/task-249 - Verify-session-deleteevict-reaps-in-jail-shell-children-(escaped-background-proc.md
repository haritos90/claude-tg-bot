---
id: TASK-249
title: "Verify session delete/evict reaps in-jail shell children (escaped background processes)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 249
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A background process started inside the shell is reliably killed when the session ends — none survive teardown.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified — no code change needed. `PersistentShell.close()` → `proc.kill()` SIGKILLs `self.proc`, which exec-chains (`setpriv→`) into `bwrap --unshare-pid` (same PID), making it PID 1 of the jail's PID namespace; the kernel then SIGKILLs every process in that namespace, including a `setsid`-DETACHED background process (a server/build the shell started) that escaped the process group. Confirmed empirically (a setsid'd bg process dies with the namespace). Documented the guarantee in `close()` so it is not re-flagged; no separate cgroup/process-group sweep is required.
<!-- SECTION:NOTES:END -->

