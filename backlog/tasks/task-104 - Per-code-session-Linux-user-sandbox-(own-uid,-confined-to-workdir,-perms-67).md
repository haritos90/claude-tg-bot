---
id: TASK-104
title: "Per-code-session Linux user sandbox (own uid, confined to workdir, perms 6/7)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 104
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Optional bubblewrap sandbox for code sessions — unprivileged, workdir-confined, secrets unreadable. Enable with `SANDBOX_CODE=1`.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Opt-in per-code-session **bubblewrap** jail (`config.SANDBOX_CODE`, default OFF). When on, code mode launches `claude` via `deploy/sandbox-claude.sh` (wired through `ClaudeAgentOptions.cli_path` in `engine._enable_sandbox`): dropped to an unprivileged uid (default 65534), filesystem confined to the session workdir (the only rw bind) + a private tmpfs HOME, the subscription credential injected READ-ONLY via `--ro-bind-data` (real `~/.claude` invisible), env wiped with `--clearenv` (no `TELEGRAM_BOT_TOKEN` leak), network kept (resolv.conf target bound so DNS resolves). Verified end-to-end: claude auths + the agent's Bash writes its workdir, while the bot `.env` / secrets / other sessions / `/root` are unreadable; bwrap's userns maps the jail uid to outer-root for host writes so the root-owned workdir is writable (no chown). **Residual P0 (owner-deferred):** the agent shares claude's process so it CAN read the injected token — blocked from escaping the workdir; egress-blocking is a future phase. Also future: cross-restart session-state persistence (HOME is tmpfs) + the perm 6/7 noexec toggle (reserved).
<!-- SECTION:NOTES:END -->

