---
id: TASK-137
title: "Fix the exit-1 startup failure + the \"Not connected\" chat-death loop + surface real errors + honest usage + sandbox file perms"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 137
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot no longer dies on a stale resume; errors say what actually went wrong; usage stops lying; sandbox files aren't world-readable.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Root cause of "Failed to start session: Command failed with exit code 1 … Check stderr output for details" was a **stale `--resume` id** ("No conversation found with session ID"), whose real message the SDK swallowed (it only pipes child stderr when `ClaudeAgentOptions.stderr` is set — the bot never set it). Fixes: (a) **capture stderr** via a `_on_stderr` ring buffer wired into options; (b) **classify + surface** the real reason — `_classify_stderr` maps it to `err.rate_limit` (limit) / generic, logs the tail, and shows it localized instead of the placeholder; (c) **auto-recover stale resume** — `_ensure_client` retries connect ONCE without `--resume` on the resume-not-found signature (never on limit/auth); (d) **"Not connected" loop** (build LOCAL client → connect → publish only on success; `_drop_client()` on every failure path so the next turn reconnects) — this was already in the tree from the audit, verified + retagged #137; (e) **honest usage** — a limit-failed turn now synthesizes a `rejected` five_hour window (`limit_hit` flag) so the footer/pin read "5h ⛔ limited" instead of a stale "5h OK", self-healing on the next success; `usage.window_str` no longer asserts "OK" for an unknown status (new `usage.status.unknown` = "—"); (f) **sandbox file perms** — `umask 077` in the launcher + host-side `chmod 0700` on the workdir/.sbxstate so the agent's outputs are owner-only (verified 600/700, root-owned under 0700 `/root`; cross-session bind isolation already correct). Smoke: py_compile+import+ruff+pytest(60) green, sandbox confinement re-verified, bot re-polling.
<!-- SECTION:NOTES:END -->

