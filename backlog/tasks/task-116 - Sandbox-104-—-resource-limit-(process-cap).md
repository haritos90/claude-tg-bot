---
id: TASK-116
title: "Sandbox #104 — resource limit (process cap)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 116
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sandboxed code can't fork-bomb the host.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The launcher sets `ulimit -u 512` before exec'ing the jail, blunting a fork-bomb DoS from sandboxed code. (seccomp + cgroup memory/CPU limits — needing a compiled BPF policy / a systemd scope — are noted as lower-priority future hardening, not shipped here.)
<!-- SECTION:NOTES:END -->

