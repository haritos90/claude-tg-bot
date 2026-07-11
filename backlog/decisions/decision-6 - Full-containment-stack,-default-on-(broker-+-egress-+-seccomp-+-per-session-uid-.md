---
id: decision-6
title: "Full containment stack, default-on (broker + egress + seccomp + per-session uid + caps)"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The jail alone still lets a compromised session reach the network with the real token and consume unbounded CPU/RAM/pids.

## Decision

Enable the full containment stack by DEFAULT: the credential broker (token leaves the jail), egress hard-blocked to loopback via a cgroup-scoped iptables rule (dev hosts via a CONNECT proxy), an x86_64 seccomp denylist, per-jail mem/CPU/pid caps, and a DISTINCT non-root host uid per session (workdir chowned to it).

## Consequences

- A code-session escape is unprivileged, offline, resource-capped, and holds no token.
- The cgroup is joined MANUALLY in the launcher (not `systemd-run --scope`, which orphans the subprocess on SIGKILL and defeats the reaper).
- seccomp denies `ptrace` → no `strace`/`gdb` in a code session. Full scheme in `docs/isolation.md`.

**Source tasks:** #119, #114, #116, #183, #195, #312
