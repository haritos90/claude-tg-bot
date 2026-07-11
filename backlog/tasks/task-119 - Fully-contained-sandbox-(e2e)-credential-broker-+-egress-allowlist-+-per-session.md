---
id: TASK-119
title: "Fully-contained sandbox (e2e): credential broker + egress allowlist + per-session isolation + DoS limits"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 119
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Optional full sandbox isolation (off by default): with it enabled, a code session's network is locked to an allowlist (your Claude usage + chosen dev hosts like GitHub/PyPI/npm), the subscription token never enters the sandbox (a host broker injects it from outside), each session can hold its own service credentials via `/secret`, and per-session memory/CPU/process limits + a syscall filter contain a misbehaving session.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Completes the sandbox on top of the bwrap FS confinement (#104) + broker (#119b). **119c egress allowlist:** the jail's egress is hard-blocked to LOOPBACK ONLY by a cgroup-scoped iptables rule (`deploy/egress-setup.sh`: a dedicated `SBX_EGRESS` chain + ONE `OUTPUT` jump matched by `-m cgroup --path sbx` — never a global rule, never the policy; fully reverted by `egress-teardown.sh`). `claude` reaches Anthropic via the broker (loopback); the agent's tools reach an allowlisted dev-host set (github/pypi/npm/anthropic, extend via `EGRESS_ALLOW_HOSTS`) through a CONNECT proxy (`deploy/egress-proxy.py`, domain dot-suffix match, tunnels TLS — no MITM); all else is dropped, so the proxy is the only exit and there is no bypass (design option E). The jail joins the cgroup in `deploy/sandbox-claude.sh` via a MANUAL `/sys/fs/cgroup/sbx/<pid>` leaf — NOT `systemd-run --scope`, which forks the target under PID 1 so a SIGKILL would orphan the ~500 MB `claude` and defeat the #179 reaper; the manual leaf keeps the tree SDK→launcher/bwrap→claude so the existing kill/reap path still works. **119d per-session secrets:** `/secret NAME=VALUE` (code sessions) stores a user-supplied service credential in `<sid>/secrets.env` (root-owned 0600, a sibling of the workdir), injected as an env var into THAT session's jail only; the owner's own credentials never enter any jail. **119e DoS:** the same cgroup leaf carries `memory.max`/`cpu.max`/`pids.max` (`SANDBOX_MEM_MB`/`SANDBOX_CPU_PERCENT`/`SANDBOX_PIDS_MAX`) and an x86_64 seccomp denylist BPF (`deploy/make-seccomp.py`, `SANDBOX_SECCOMP`) refuses ~29 exotic syscalls (ptrace/bpf/kexec/keyctl/module-load/userfaultfd/…) via `bwrap --seccomp`. All OS/network mechanism lives in `deploy/` shell+standalone (Component 5); Python only sets `SBX_*` env + runs the sidecars (`bot.main` starts the broker + egress proxy, sets up/reverts the firewall, compiles the seccomp blob). SHIPPED OPT-IN (off by default, like the broker): enable with `CRED_BROKER=1` + `SANDBOX_EGRESS=1` (+ optional `SANDBOX_SECCOMP=1`, `SANDBOX_MEM_MB`, `SANDBOX_CPU_PERCENT`, `SANDBOX_PIDS_MAX`). Verified e2e through the real launcher: a real `claude` turn completed via the broker (`POST /v1/messages → 200`) with the jail credential = `BROKER-PLACEHOLDER` (real token ABSENT); allowlisted host reachable via the proxy, non-allowlisted host refused (proxy DENY/403), direct exfil bypassing the proxy BLOCKED, seccomp denied add_key/bpf/ptrace/userfaultfd (EPERM) while echo + `claude --version` (node) start clean. +6 tests, 140 green, ruff clean.
<!-- SECTION:NOTES:END -->

