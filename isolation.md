# Sandbox & isolation architecture (#104 + #119)

How a session is contained: what an untrusted `code`-level user (driving the
agent) **cannot** do, and the mechanism behind each guarantee. This is the deep
reference; [`AGENTS.md`](AGENTS.md) §5 *Sandbox* is the summary and
[`TODO.md`](TODO.md) #119 holds the threat model + design rationale.

**The jail is MANDATORY for every session — chat AND code, no exceptions (#231).** There
is no per-session opt-out and no toggle (the `/sandbox` command and the `/settings` Sandbox
row were retired in #231; `no_sandbox` is never set). `claude` is jailed identically in both
modes; the only mode difference is that the egress allowlist + cgroup DoS limits (§5–§6)
apply to **code** sessions only — a `chat` session has no Bash/file surface to leak and needs
open egress for `WebFetch`. The jail, per-session uid, broker (§3) and seccomp (§6) apply to
**all** modes regardless.

The layers are **independent**. The bare bubblewrap jail (#104/#180) is **always on** and
confines the filesystem; the four #119 layers (broker, egress, secrets, DoS/seccomp) are
deployer-gated in `.env` (all **enabled on this deployment**) and turn the jail into real
containment for a semi-trusted user.

---

## 1. The picture

```
                          HOST (service user = root)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  ~/.claude/.credentials.json   ← the REAL subscription OAuth token        │
  │        ▲ refreshed before expiry by token_refresh.py (#191)              │
  │        │ read fresh (on mtime change)                                     │
  │   ┌────┴───────────────┐         ┌──────────────────────┐                │
  │   │ cred-broker.py      │        │ egress-proxy.py        │                │
  │   │ 127.0.0.1:8789      │        │ 127.0.0.1:8790         │                │
  │   │ swaps Authorization │        │ CONNECT domain         │                │
  │   │ → real Bearer       │        │ allowlist (no MITM)    │                │
  │   └────▲────────────────┘        └────▲───────────────────┘                │
  │        │ HTTP (loopback only)         │ HTTP CONNECT (loopback only)       │
  │  ══════╪══════════════════════════════╪══════ iptables: cgroup `sbx`      │
  │        │   the ONLY two allowed exits  │        egress = loopback ONLY      │
  │  ┌─────┴───────────────────────────────┴─────────────────────────────┐    │
  │  │  bubblewrap jail  (cgroup /sys/fs/cgroup/sbx/<pid>)                 │    │
  │  │   • inner uid 65534 → a DISTINCT non-root HOST uid per session       │    │
  │  │   • FS = only this session's work/ is writable; root read-only      │    │
  │  │   • ~/.claude/.credentials.json = "BROKER-PLACEHOLDER" (a DUMMY)     │    │
  │  │   • ANTHROPIC_BASE_URL=http://127.0.0.1:8789  (→ broker)            │    │
  │  │   • HTTPS_PROXY=http://127.0.0.1:8790         (→ egress proxy)      │    │
  │  │   • <session secrets> injected as env vars (#119d)                  │    │
  │  │   • seccomp denylist + memory/cpu/pids caps (#119e)                 │    │
  │  │            claude  (native binary) ── runs the agent + its Bash ──   │    │
  │  └────────────────────────────────────────────────────────────────────┘    │
  └─────────────────────────────────────────────────────────────────────────┘
       to api.anthropic.com  ◀── only the broker/proxy reach the internet
```

The agent inside the jail can talk to **exactly two** loopback ports — the broker
and the egress proxy. Anything else (a direct socket to `evil.com`, DNS, a second
proxy) is dropped by the firewall. The real token is never inside the jail.

---

## 2. Layer 0 — the bubblewrap jail (#104 / #180, on by default)

`engine._enable_sandbox` points the SDK's `cli_path` at
[`deploy/sandbox-claude.sh`](deploy/sandbox-claude.sh), which `exec`s `bwrap` with:

- `--unshare-user --uid 65534` — the agent runs as an unprivileged uid INSIDE the jail.
  By default the userns maps that to the outer service uid (root); with
  `SANDBOX_PER_SESSION_UID` on (the recommended posture) the launcher instead runs bwrap
  via `setpriv` as a DISTINCT non-root HOST uid per session (`SANDBOX_UID_BASE` +
  `int(sid,16) % SANDBOX_UID_RANGE`) and chowns the session's `work/` + `state/` to it.
  So a userns/kernel escape lands as an unprivileged user (not host root) AND cannot read
  another session's files (owned by a different uid, mode `0700`). This requires
  `BASE_WORKDIR` outside the root-only `/root` — it is `/var/lib/claude-tg-bot/workdirs`,
  and the CLI is staged world-readably at `/usr/local/bin/claude` (the jail can't reach
  `~/.local` as a non-root uid).
- FS confinement — only the session's `work/` dir is bind-mounted writable; `/usr`,
  `/bin`, `/etc` are read-only; the root is `--remount-ro`. No other session, no
  `.env`, no `/root` is visible.
- `--clearenv` — the bot's env (incl. `TELEGRAM_BOT_TOKEN`) never reaches the agent.
- a private tmpfs `HOME`; `~/.claude/projects` is bind-mounted from the per-session
  `state/` dir so `resume` survives a rebuild (#115/#181).

This bounds **filesystem** blast radius. On its own it does **not** stop network
exfiltration or protect the token — that's what #119 adds.

---

## 3. Layer 1 — the credential broker (#119b, `CRED_BROKER=1`)

**Goal:** the subscription OAuth token must be *un-extractable* by the agent — and a
firewall alone can't do that (the agent can `cat` the token and the bot streams its
output back to the user; or POST it to an *allowed* host). So the token must not be
in the jail at all.

**Mechanism** ([`deploy/cred-broker.py`](deploy/cred-broker.py), a host sidecar
started by `bot.main`):

1. The launcher gives the jail a **dummy** credentials file
   (`accessToken = "BROKER-PLACEHOLDER"`, a far-future `expiresAt`) on an
   unlinked tmpfs fd, plus `ANTHROPIC_BASE_URL=http://127.0.0.1:8789`.
2. `claude` POSTs its API calls to the broker on loopback with
   `Authorization: Bearer BROKER-PLACEHOLDER`.
3. The broker **drops that header and substitutes the real OAuth Bearer**, read from
   the host's `~/.claude/.credentials.json`, and forwards to `api.anthropic.com`,
   streaming the SSE reply back (chunked).

So the subscription is *usable* (via the broker) but the real token is never readable
inside the jail — there is nothing real to print, `cat`, or POST.

### Why plaintext HTTP to the broker is correct (and safe)

We did **not** add an "insecure" flag. The Claude Code CLI (Node/undici) simply honours
the **scheme of `ANTHROPIC_BASE_URL`**: an `http://` base URL ⇒ a plaintext HTTP
request; `https://` ⇒ TLS. Recon #119a confirmed the CLI honours `ANTHROPIC_BASE_URL`
under OAuth/subscription auth and POSTs `/v1/messages?beta=true` with
`Authorization: Bearer …` + the `anthropic-beta`/`anthropic-version` headers. Pointing
it at `http://127.0.0.1:8789` therefore yields plaintext to the broker — no MITM
certificate, no TLS-termination needed (this is "variant a" of the design).

It is safe because that plaintext hop **never leaves the box**: it traverses only the
host loopback (the jail shares the host network namespace, so `127.0.0.1` is the host's
loopback). The broker re-originates a real **HTTPS** connection to Anthropic. A
plaintext request that only ever exists on `lo` cannot be sniffed off a wire.

### The token never goes stale

Three independent facts, none of which the broker breaks:

- **On disk:** `token_refresh.py` (#191) renews the access token before its ~8 h
  expiry (sweep every 30 min, renew when <1 h of life remains). Runs whether or not
  the broker is on.
- **In the broker:** `_Creds.token()` re-reads the credentials file whenever its
  `mtime` changes, so it always forwards the *current* token and picks up #191's
  rotation on the fly — it never caches a stale one.
- **In the jail:** the dummy carries a far-future expiry, so the inner CLI never tries
  to refresh it (a refresh with a bogus token would hit the real OAuth host and fail).

The broker does **not** refresh the token itself — #191 does — but it always forwards
a fresh one. The only residual case is "#191 itself dies *and* the token expires," in
which the broker forwards an expired token and Anthropic returns 401 — exactly the
pre-broker behaviour. So the broker adds **no** staleness risk; #191 removes it.
(A belt-and-suspenders 401-triggered refresh inside the broker is a possible future
hardening, but would duplicate #191.)

**P0:** the broker forwards an OAuth Bearer only and refuses to start if an
`ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` is in its env — it can never flip billing to
paid per-token.

---

## 4. Layer 2 — the egress allowlist (#119c, `SANDBOX_EGRESS=1`)

**Goal:** even with no token in the jail, don't let the box reach arbitrary hosts (an
attack relay / a data-exfil store), while still allowing chosen dev services.

**Scope: CODE sessions only.** Egress (and the cgroup DoS limits in §6) apply to `code`
sessions — the Bash/file-capable exfil surface the threat model targets. A `chat`
session carries only the read-only web tools (no Bash, no host data to leak), so egress
there adds ~no security but would break `WebFetch` (it fetches arbitrary URLs
client-side) by blocking everything off the allowlist — so chat keeps open egress. The
broker (§3) and seccomp (§6) still apply to **every** session, so the token is out of
every jail regardless of mode.

**Mechanism — option E (domain filtering + a hard no-bypass block):**

1. **cgroup placement.** [`deploy/sandbox-claude.sh`](deploy/sandbox-claude.sh) puts the
   jail into a **manually-created** cgroup leaf `/sys/fs/cgroup/sbx/<pid>` (writes its
   own PID to `cgroup.procs`, then `exec bwrap` — the same PID becomes bwrap, and
   `claude` inherits the cgroup). It is **not** `systemd-run --scope`: a scope forks the
   target under PID 1, so a `SIGKILL` on the SDK's child would orphan the ~500 MB
   `claude` and defeat the idle reaper (#179). The manual leaf keeps the process tree
   `SDK → launcher/bwrap → claude` intact so the existing kill/reap path still works.
2. **The firewall** ([`deploy/egress-setup.sh`](deploy/egress-setup.sh)) creates a
   **dedicated** `SBX_EGRESS` iptables chain and **one** `OUTPUT` jump that fires only
   for that cgroup: `iptables -I OUTPUT -m cgroup --path sbx -j SBX_EGRESS`. Inside the
   chain: ACCEPT loopback to the broker (8789) + proxy (8790); REJECT everything else.
   IPv6 egress from the cgroup is rejected wholesale. **It never touches the OUTPUT
   policy or any other chain** — SSH, the bot, Docker are never matched — and it is
   fully reverted by [`deploy/egress-teardown.sh`](deploy/egress-teardown.sh). The match
   is by **cgroup, not uid**: the jail runs `--uid 65534`, so from the host the socket's
   owner is outer-root and a `--uid` match would miss.
3. **The proxy** ([`deploy/egress-proxy.py`](deploy/egress-proxy.py)) is a tiny
   loopback CONNECT proxy: it allows `CONNECT host:443` only for an allowlisted set of
   hosts (`api.anthropic.com`, `github.com`, `pypi.org`, `npmjs.org`, … + anything in
   `EGRESS_ALLOW_HOSTS`, matched by exact host or dot-suffix), **tunnels** the TLS (no
   MITM), and refuses the rest with `403`. A domain allowlist beats an IP allowlist
   because the API/registries are CDN-fronted (rotating IPs, shared ranges → fragile +
   leaky).

So the jail can reach **only** the broker and the proxy on loopback; the proxy is the
only path to the internet and it is domain-restricted; a tool that ignores
`HTTPS_PROXY` and dials out directly is dropped by the firewall (no bypass).

---

## 5. Layer 3 — per-session secrets (#119d, `/secret`)

A `code` user runs `/secret NAME=VALUE` (code sessions only) to store **their own**
service credential (e.g. a GitHub token for `git push`). It is written to
`<sid>/secrets.env` (root-owned `0600`, a **sibling** of the agent's `work/` dir, so the
agent can't read the file itself), and the launcher injects each `KEY=VALUE` as an env
var (`--setenv`) into **that session's jail only**. Keys are validated
(`^[A-Za-z_][A-Za-z0-9_]*$`); values are never echoed back.

The **owner's** own credentials never enter any jail. A user leaking their own
credential is their problem, not the owner's (the #119 threat model). `/secret clear`
wipes them; `/secret clear NAME` removes one.

---

## 6. Layer 4 — DoS limits + seccomp (#119e)

- **cgroup limits** on the same leaf: `memory.max` / `cpu.max` / `pids.max` from
  `SANDBOX_MEM_MB` / `SANDBOX_CPU_PERCENT` (% of one core) / `SANDBOX_PIDS_MAX`
  (0 = unlimited). Plus the always-on `ulimit -u 512` (#116).
- **seccomp** (`SANDBOX_SECCOMP=1`): [`deploy/make-seccomp.py`](deploy/make-seccomp.py)
  compiles an **x86_64 denylist** BPF that returns `EPERM` for ~29 exotic, high-blast
  syscalls (`ptrace`, `bpf`, `kexec_*`, `keyctl`/`add_key`, module-load, `userfaultfd`,
  `perf_event_open`, time-set, …), loaded via `bwrap --seccomp`. It's a **denylist**
  (default = allow) so it can't break ordinary node/git/python work; the goal is to
  shrink the kernel attack surface. On a non-x86_64 arch it emits nothing (skipped).

---

## 7. Where the data lives

| Item | Location | In the DB? | In the jail? |
|---|---|---|---|
| Subscription OAuth token | `~/.claude/.credentials.json` (host, service user), refreshed by #191 | **No** | **No** — broker mode injects a `BROKER-PLACEHOLDER` dummy (ephemeral tmpfs); raw-jail mode binds it read-only |
| Per-session user secrets (#119d) | `BASE_WORKDIR/<sid>/secrets.env` (root `0600`) | No | Injected as **env vars** only (values, not the file) |
| Session metadata / toggles | `bot.db` → `threads` etc. | Yes | No |
| Agent's files | `BASE_WORKDIR/<sid>/work/` (owned by the session's host uid, `0700`) | No | Yes (the only writable bind) |
| Transcript | `BASE_WORKDIR/<sid>/state/` → `~/.claude/projects` | No | Bound at HOME, but `state/` itself is not reachable by the agent's tools |

`BASE_WORKDIR` is `/var/lib/claude-tg-bot/workdirs` (outside the root-only `/root`, so a
non-root jail uid can reach its own `work/`). The bot's own secrets
(`TELEGRAM_BOT_TOKEN`, allowlist) live in `.env` / `allowlist.json` and are wiped from
the jail by `--clearenv`. Full storage layout + SQLite schema: [`data-model.md`](data-model.md).

---

## 8. One client (and one jail) per **session**, not per user

Each session (`thread_id`) has its **own** `engine.ClaudeSession` over the SDK — its
own `claude` subprocess, its own `resume` session id, its own `work/` dir, its own
cgroup leaf, and its own `secrets.env`. A user with three sessions has three
independent clients/jails; there is no shared-per-user client. Live subprocesses are
capped (`MAX_LIVE_CLIENTS`) and idle-reaped (#179) — history persists on disk, so a
reaped session rebuilds (resumes) on its next message.

---

## 9. Dependencies

**No new Python packages** (`requirements.txt` is unchanged — stdlib only for the
broker/proxy/seccomp helpers: `socket`, `select`, `http.client`, `http.server`,
`struct`, `threading`).

System tools (already present on a typical Debian/systemd VPS):

- **bubblewrap** (`apt install bubblewrap`) — the jail (any sandbox use).
- **iptables** (the `iptables-nft` backend is fine) + the **`xt_cgroup`** kernel module
  (auto-`modprobe`d by `egress-setup.sh`) — only for `SANDBOX_EGRESS`.
- **cgroup v2** (the unified hierarchy, standard under systemd) — for egress + DoS
  limits.
- `nftables` is **not** required (we use `iptables -m cgroup --path`).

---

## 10. Enabling it

In `.env`, then restart (`systemctl restart claude-tg-bot`):

```bash
CRED_BROKER=1              # token leaves the jail (recommended first)
SANDBOX_EGRESS=1           # loopback-only egress + the dev-host CONNECT proxy (code sessions)
EGRESS_ALLOW_HOSTS=git.example.com,internal.registry   # optional extra hosts
SANDBOX_SECCOMP=1          # x86_64 syscall denylist (optional; blocks ptrace → no strace/gdb)
SANDBOX_MEM_MB=1536        # per-jail memory cap (optional; 0 = unlimited)
SANDBOX_CPU_PERCENT=150    # 1.5 cores (optional)
SANDBOX_PIDS_MAX=512       # per-jail process cap (optional)
SANDBOX_PER_SESSION_UID=1  # run each jail as a distinct non-root host uid (escape hardening)
```

`SANDBOX_PER_SESSION_UID` requires `BASE_WORKDIR` outside `/root` (default
`/var/lib/claude-tg-bot/workdirs`); the bot stages the CLI at `/usr/local/bin/claude` for
the unprivileged jails. The recommended combo to graduate a semi-trusted `code` user is
`CRED_BROKER=1` + `SANDBOX_EGRESS=1` + `SANDBOX_PER_SESSION_UID=1`. Note that the egress
allowlist also restricts the **owner's** own code sessions to the allowlisted hosts —
extend it with `EGRESS_ALLOW_HOSTS`.

The launcher reads its config from `SBX_*` env vars that `engine._enable_sandbox` sets
(`SBX_BROKER_URL`, `SBX_PROXY_URL`, `SBX_USE_CGROUP`, `SBX_MEM_MAX`, `SBX_CPU_MAX`,
`SBX_PIDS_MAX`, `SBX_SECCOMP`, `SBX_SECRETS_ENV`) — the single Python⇄shell interface.

---

## 11. Build gotchas

See the memory note `sandbox-119-build-gotchas` and [`AGENTS.md`](AGENTS.md) §5 for the
traps (manual cgroup vs `systemd-run`; the seccomp fall-through-must-be-ALLOW bug; the
`iptables -m cgroup --path` "dir must exist + module loaded" requirement; the
egress-proxy ASCII-decode trap).
