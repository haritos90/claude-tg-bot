# Security Policy

This is a personal Telegram bot that runs **Bash / Write / Edit on the host** and
holds a Telegram bot token plus a Claude Pro/Max **subscription session**. A flaw
here can leak those secrets or hand an attacker a shell, so reports are taken
seriously and handled privately.

## Reporting a vulnerability

**Do not open a public issue, PR, or discussion for a security problem** —
disclosing it publicly puts every operator running this code at risk before a fix
is out.

Instead, use GitHub's private reporting: open the repository's **Security** tab →
**Report a vulnerability** (this files a private security advisory visible only to
the maintainer). Please include:

- **Impact** — what an attacker can read, run, bypass, or bill.
- **Proof of concept / steps to reproduce** — the exact commands, messages, or
  callback data; the smallest sequence that triggers it.
- **Affected version / commit** — branch and commit SHA (and Agent SDK version if
  relevant).
- **Environment** — Python version, OS, and how the bot is run (`python -m app`
  vs. the systemd unit).

**Redact your own secrets first.** Strip the bot token, your numeric Telegram
user id(s), and any `allowlist.json` contents from logs and screenshots before
attaching them — the report is to fix the bug, not to expose your deployment.

## Scope

This repository is the bot itself: the aiogram polling app, the `i18n` / `db` /
`access` / `permissions` layers, and the `engine` wrapper around the
`claude-agent-sdk`. It runs on the operator's own host against their Claude
subscription — there is no Anthropic API key and no per-token billing by design.

## In scope

- Leakage of the **Telegram bot token**, the **`allowlist.json`** contents, or the
  **Claude subscription session** (e.g. through logs, error messages, or replies).
- **Permission-gate bypass** — getting Bash / Write / Edit (or any tool outside
  `permissions.SAFE_TOOLS`) to execute in code mode **without** the inline
  **Allow** tap, or an approval honored from a **non-owner**.
- **Sandbox escape** (`SANDBOX_CODE`, on by default) — breaking out of the
  bubblewrap workdir confinement to read host files outside the session workdir, or
  another session's data.
- The **allowlist failing open** — a missing, empty, or corrupt `allowlist.json`,
  or a forged/spoofed identity, granting access to anyone beyond the owner.
- Anything that **forces paid API billing** — most importantly `ANTHROPIC_API_KEY`
  (or `ANTHROPIC_AUTH_TOKEN`) reaching the spawned `claude` child environment, so
  the subscription is silently bypassed.
- Cross-session **isolation breaks** — context, cwd, or session id from one
  session reaching another (`setting_sources=[]` is part of this boundary).

## Known limitations (by design — no need to report)

The server operator can read all session data. Every session's transcript and its code-mode files
live on the host — in `bot.db` and under `BASE_WORKDIR` — readable by whoever runs the bot. Grant
`code` level only to people you trust, and treat hosting others' sessions as being trusted with their
data.

Code mode is a shell running as an unprivileged, jailed user. The jail and its containment stack —
credential broker, egress allowlist, per-session uid, seccomp, cgroup caps — are part of the project,
so the subscription token stays out of the jail and a code session's egress is allowlisted; a layer a
host cannot support can be disabled through its `.env` flag. The mechanism and threat model are in
[`isolation.md`](isolation.md); report a gap there through the process above.

## Out of scope

- The upstream **`claude-agent-sdk`** and **Anthropic services** themselves —
  report those to [anthropics/claude-code](https://github.com/anthropics/claude-code)
  or Anthropic.
- The **operator's own host** and **`claude` CLI login** (the local
  `~/.claude` subscription credentials) — securing the server and that login is the
  operator's responsibility.
- **Social engineering** and **physical access** to the host or the operator's
  Telegram account.
