# Sandbox & isolation architecture

How a session is contained: what an untrusted `code`-level user (driving the
agent) cannot do, and the mechanism behind each guarantee.

Every session runs inside the jail — it is part of how the bot runs a session, not an
add-on. `claude` is jailed identically in both modes; the only mode difference is that the
egress allowlist and cgroup DoS limits (§4 + §6) apply to code sessions only — a `chat`
session has no Bash/file surface to leak and needs open egress for `WebFetch`. The jail,
per-session uid, broker (§3), and seccomp (§6) apply to all modes.

The bubblewrap jail confines the filesystem; the credential broker, egress allowlist,
per-session uid, and DoS/seccomp caps build real containment on top of it. All of it is part
of the project and runs by default. A layer a host cannot support can be turned off through
its `.env` flag (`CRED_BROKER`, `SANDBOX_EGRESS`, `SANDBOX_SECCOMP`,
`SANDBOX_PER_SESSION_UID` = `0`), but the project runs with them on.

---

## 1. The picture

```
                          HOST (service user = root)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  ~/.claude/.credentials.json   ← the REAL subscription OAuth token      │
  │        ▲ refreshed before expiry by token_refresh.py                    │
  │        │ read fresh (on mtime change)                                   │
  │   ┌────┴───────────────┐        ┌──────────────────────┐                │
  │   │ cred-broker.py     │        │ egress-proxy.py      │                │
  │   │ 127.0.0.1:8789     │        │ 127.0.0.1:8790       │                │
  │   │ swaps Authorization│        │ CONNECT domain       │                │
  │   │ → real Bearer      │        │ allowlist (no MITM)  │                │
  │   └────▲───────────────┘        └──────▲───────────────┘                │
  │        │ HTTP (loopback only)          │ HTTP CONNECT (loopback only)   │
  │  ══════╪═══════════════════════════════╪══════ iptables: cgroup `sbx`   │
  │        │   the ONLY two allowed exits  │         egress = loopback ONLY │
  │  ┌─────┴───────────────────────────────┴─────────────────────────────┐  │
  │  │  bubblewrap jail  (cgroup /sys/fs/cgroup/sbx/<pid>)               │  │
  │  │   • inner uid 65534 → a DISTINCT non-root HOST uid per session    │  │
  │  │   • FS = only this session's work/ is writable; root read-only    │  │
  │  │   • ~/.claude/.credentials.json = "BROKER-PLACEHOLDER" (a DUMMY)  │  │
  │  │   • ANTHROPIC_BASE_URL=http://127.0.0.1:8789  (→ broker)          │  │
  │  │   • HTTPS_PROXY=http://127.0.0.1:8790         (→ egress proxy)    │  │
  │  │   • <session secrets> injected as env vars                        │  │
  │  │   • seccomp denylist + memory/cpu/pids caps                       │  │
  │  │      claude  (native binary) ── runs the agent + its Bash ──      │  │
  │  └───────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────┘
       to api.anthropic.com  ◀── only the broker/proxy reach the internet
```

The agent inside the jail can talk to two loopback ports — the broker
and the egress proxy. Anything else is dropped by the firewall.

---

## 2. Layer 0 — the bubblewrap jail

`engine._enable_sandbox` points the SDK's `cli_path` at
[`deploy/sandbox-claude.sh`](../deploy/sandbox-claude.sh), which `exec`s `bwrap` with:

- `--unshare-user --uid 65534` — the agent runs as an unprivileged uid INSIDE the jail.
  By default the users maps that to the outer service uid (root); with
  `SANDBOX_PER_SESSION_UID` on the launcher instead runs bwrap
  via `setpriv` as a DISTINCT non-root HOST uid per session and chowns the
  session's `work/` + `state/` to it.
  A userns/kernel escape lands as an unprivileged user (not host root) and cannot read
  another session's files (owned by a different uid, mode `0700`). This requires
  `BASE_WORKDIR` outside the root-only `/root` — it is `/var/lib/claude-tg-bot/workdirs`,
  and the CLI is staged world-readably at `/usr/local/bin/claude` (the jail can't reach
  `~/.local` as a non-root uid).
- FS confinement — only the session's `work/` dir is bind-mounted writable; `/usr`,
  `/bin`, `/etc` are read-only; the root is `--remount-ro`.
- `--clearenv` — the bot's env (incl. `TELEGRAM_BOT_TOKEN`) never reaches the agent.
- a private tmpfs `HOME`; `~/.claude/projects` is bind-mounted from the per-session
  `state/` dir so `resume` survives a rebuild.

---

## 3. Layer 1 — the credential broker (`CRED_BROKER`)

**Goal:** the subscription OAuth token must be *un-extractable* by the agent — and a
firewall alone can't do that (the agent can `cat` the token and the bot streams its
output back to the user; or POST it to an *allowed* host). So the token must not be
in the jail at all.

**Mechanism** ([`deploy/cred-broker.py`](../deploy/cred-broker.py), a host sidecar
started by `bot.main`):

1. The launcher gives the jail a dummy credentials file
   (`accessToken = "BROKER-PLACEHOLDER"`, a far-future `expiresAt`) on an
   unlinked tmpfs fd, plus `ANTHROPIC_BASE_URL=http://127.0.0.1:8789`.
2. `claude` POSTs its API calls to the broker on loopback with
   `Authorization: Bearer BROKER-PLACEHOLDER`.
3. The broker drops that header and substitutes the real OAuth Bearer, read from
   the host's `~/.claude/.credentials.json`, and forwards to `api.anthropic.com`,
   streaming the SSE reply back (chunked).

### The token refresh

- **On disk:** `token_refresh.py` renews the access token before its ~8 h
  expiry (sweep every 30 min, renew when <1 h of life remains). Runs whether or not
  the broker is on.
- **In the broker:** `_Creds.token()` re-reads the credentials file whenever its
  `mtime` changes, so it always forwards the *current* token and picks up rotation
  on the fly.
- **In the jail:** the dummy carries a far-future expiry, so the inner CLI never tries
  to refresh it (a refresh with a bogus token would hit the real OAuth host and fail).

**P0:** the broker forwards an OAuth Bearer only and refuses to start if an
`ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` is in its env — it can't flip billing to
paid per-token.

---

## 4. Layer 2 — the egress allowlist (`SANDBOX_EGRESS`)

**Goal:** even with no token in the jail, don't let the box reach arbitrary hosts (an
attack relay / a data-exfil store), while still allowing chosen dev services.

**Scope: CODE sessions only.** Egress (and the cgroup DoS limits in §6) apply to `code`
sessions — the Bash/file-capable exfil surface the threat model targets. A `chat`
session carries only the read-only web tools (no Bash, no host data to leak), so egress
there adds ~no security but would break `WebFetch` (it fetches arbitrary URLs
client-side) by blocking everything off the allowlist — so chat keeps open egress. The
broker (§3) and seccomp (§6) still apply to every session, so the token is out of
every jail regardless of mode.

**Mechanism:**

1. **cgroup placement.** [`deploy/sandbox-claude.sh`](../deploy/sandbox-claude.sh) puts the
   jail into a manually-created cgroup leaf `/sys/fs/cgroup/sbx/<pid>` (writes its
   own PID to `cgroup.procs`, then `exec bwrap` — the same PID becomes bwrap, and
   `claude` inherits the cgroup). It isn't `systemd-run --scope`: a scope forks the
   target under PID 1, so a `SIGKILL` on the SDK's child would orphan the ~500 MB
   `claude` and defeat the idle reaper. The manual leaf keeps the process tree
   `SDK → launcher/bwrap → claude` intact so the existing kill/reap path still works.
2. **The firewall** ([`deploy/egress-setup.sh`](../deploy/egress-setup.sh)) creates a
   dedicated `SBX_EGRESS` iptables chain and one `OUTPUT` jump that fires only
   for that cgroup: `iptables -I OUTPUT -m cgroup --path sbx -j SBX_EGRESS`. Inside the
   chain: ACCEPT loopback to the broker (8789) + proxy (8790); REJECT everything else.
   IPv6 egress from the cgroup is rejected wholesale. It never touches the OUTPUT
   policy or any other chain — SSH, the bot, Docker are never matched — and it is
   fully reverted by [`deploy/egress-teardown.sh`](../deploy/egress-teardown.sh). The match
   is by cgroup: the jail runs `--uid 65534`, so from the host the socket's
   owner is outer-root and a `--uid` match would miss.
3. **The proxy** ([`deploy/egress-proxy.py`](../deploy/egress-proxy.py)) is a tiny
   loopback CONNECT proxy: it allows `CONNECT host:443` only for an allowlisted set of
   hosts (`api.anthropic.com`, `github.com`, `pypi.org`, `npmjs.org`, … + anything in
   `EGRESS_ALLOW_HOSTS`, matched by exact host or dot-suffix), tunnels the TLS (no
   MITM), and refuses the rest with `403`. A domain allowlist beats an IP allowlist
   because the API/registries are CDN-fronted (rotating IPs, shared ranges → fragile +
   leaky).

So the jail can reach only the broker and the proxy on loopback; the proxy is the
only path to the internet and it is domain-restricted; a tool that ignores
`HTTPS_PROXY` and dials out directly is dropped by the firewall (no bypass).

---

## 5. Layer 3 — per-session secrets (`/secret`)

A `code` user runs `/secret NAME=VALUE` (code sessions only) to store **their own**
service credential (e.g. a GitHub token for `git push`). It is written to
`<sid>/secrets.env` (root-owned `0600`, a sibling of the agent's `work/` dir, so the
agent can't read the file itself), and the launcher injects each `KEY=VALUE` as an env
var (`--setenv`) into that session's jail only. Keys are validated
(`^[A-Za-z_][A-Za-z0-9_]*$`).

The owner's own credentials never enter any jail. A user leaking their own
credential is their problem, not the owner's. `/secret clear`
wipes them; `/secret clear NAME` removes one.

---

## 6. Layer 4 — DoS limits + seccomp

- **cgroup limits** on the same leaf: `memory.max` / `cpu.max` / `pids.max` from
  `SANDBOX_MEM_MB` / `SANDBOX_CPU_PERCENT` (% of one core) / `SANDBOX_PIDS_MAX`
  (0 = unlimited). Plus the always-on `ulimit -u 512`.
- **seccomp** (`SANDBOX_SECCOMP=1`): [`deploy/make-seccomp.py`](../deploy/make-seccomp.py)
  compiles an x86_64 denylist BPF that returns `EPERM` for ~29 exotic, high-blast
  syscalls (`ptrace`, `bpf`, `kexec_*`, `keyctl`/`add_key`, module-load, `userfaultfd`,
  `perf_event_open`, time-set, …), loaded via `bwrap --seccomp`. It's a denylist
  (default = allow) so it can't break ordinary node/git/python work; the goal is to
  shrink the kernel attack surface. On a non-x86_64 arch it emits nothing (skipped).

---

## 7. Where the data lives

| Item | Location | In the DB? | In the jail? |
|---|---|---|---|
| Subscription OAuth token | `~/.claude/.credentials.json` (host, service user), refreshed by `token_refresh.py` | **No** | **No** — broker mode injects a `BROKER-PLACEHOLDER` dummy (ephemeral tmpfs); raw-jail mode binds it read-only |
| Per-session user secrets | `BASE_WORKDIR/<sid>/secrets.env` (root `0600`) | No | Injected as **env vars** only (values, not the file) |
| Session metadata / toggles | `bot.db` → `threads` etc. | Yes | No |
| Agent's files | `BASE_WORKDIR/<sid>/work/` (owned by the session's host uid, `0700`) | No | Yes (the only writable bind) |
| Transcript | `BASE_WORKDIR/<sid>/state/` → `~/.claude/projects` | No | Bound at HOME, but `state/` itself is not reachable by the agent's tools |

`BASE_WORKDIR` is `/var/lib/claude-tg-bot/workdirs` (outside the root-only `/root`, so a
non-root jail uid can reach its own `work/`). The bot's own secrets
(`TELEGRAM_BOT_TOKEN`, allowlist) live in `.env` / `allowlist.json` and are wiped from
the jail by `--clearenv`. Full storage layout + SQLite schema: [`data-model.md`](data-model.md).

---

## 8. One client (and one jail) per **session**

Each session (`thread_id`) has its own `engine.ClaudeSession` over the SDK — its
own `claude` subprocess, its own `resume` session id, its own `work/` dir, its own
cgroup leaf, and its own `secrets.env`. A user with three sessions has three
independent clients/jails; there is no shared-per-user client. Live subprocesses are
capped (`MAX_LIVE_CLIENTS`) and idle-reaped — history persists on disk, so a
reaped session rebuilds (resumes) on its next message.

---

## 9. Dependencies

System tools:

- **bubblewrap** (`apt install bubblewrap`) — the jail (any sandbox use).
- **iptables** (the `iptables-nft` backend is fine) + the **`xt_cgroup`** kernel module
  (auto-`modprobe`d by `egress-setup.sh`) — only for `SANDBOX_EGRESS`.
- **cgroup v2** (the unified hierarchy, standard under systemd) — for egress + DoS
  limits.
- `nftables` isn't required (the egress rule uses `iptables -m cgroup --path`).

---

## 10. The `.env` flags

The layers run by default. Set a flag to `0` in `.env` and restart
(`systemctl restart claude-tg-bot`) to disable one on a host that can't support it; the caps
take a value:

```bash
SANDBOX_CODE=1             # default; master switch for the whole sandbox stack (deployer kill-switch)
CRED_BROKER=1              # default; keeps the token out of the jail (0 binds it read-only instead)
SANDBOX_EGRESS=1           # default; loopback-only egress + the dev-host CONNECT proxy (code sessions)
SANDBOX_SECCOMP=1          # default; x86_64 syscall denylist (blocks ptrace → no strace/gdb)
SANDBOX_PER_SESSION_UID=1  # default; a distinct non-root host uid per jail
SANDBOX_MEM_MB=1536        # per-jail memory cap (0 = unlimited)
SANDBOX_CPU_PERCENT=150    # 1.5 cores
SANDBOX_PIDS_MAX=512       # per-jail process cap (0 = unlimited)
SANDBOX_EXEC=1             # default; workdir mounted executable (0 = noexec working tree)
SANDBOX_UID_BASE=700000    # first host uid of the per-session range
SANDBOX_UID_RANGE=60000    # size of the per-session uid range
SANDBOX_UID=65534          # single fallback uid when per-session uids are off
CRED_BROKER_PORT=8789      # loopback port of the credential-broker sidecar
EGRESS_PROXY_PORT=8790     # loopback port of the CONNECT allowlist proxy
EGRESS_ALLOW_HOSTS=git.example.com,internal.registry   # extra CONNECT-allowlisted hosts
```

`SANDBOX_PER_SESSION_UID` requires `BASE_WORKDIR` outside `/root` (e.g.
`/var/lib/claude-tg-bot/workdirs`); the bot stages the CLI at `/usr/local/bin/claude` for
the unprivileged jails. The egress allowlist also restricts the owner's own code sessions to
the allowlisted hosts — extend it with `EGRESS_ALLOW_HOSTS`.

The launcher reads its config from `SBX_*` env vars that `engine._enable_sandbox` sets
(`SBX_BROKER_URL`, `SBX_PROXY_URL`, `SBX_USE_CGROUP`, `SBX_MEM_MAX`, `SBX_CPU_MAX`,
`SBX_PIDS_MAX`, `SBX_SECCOMP`, `SBX_SECRETS_ENV`) — the single Python⇄shell interface.

---

## 11. Build gotchas

The traps: manual cgroup leaf vs `systemd-run` and the seccomp fall-through-must-be-ALLOW
bug (both in the Sandbox section of [`gotchas.md`](gotchas.md)); the
`iptables -m cgroup --path` "dir must exist + module loaded" requirement; the
egress-proxy ASCII-decode trap.

---

## 12. Threat model & design rationale

The goal is a sandbox a
semi- to untrusted code-level user (driving the agent and seeing its output) cannot
use to (a) break the server, (b) steal the owner's data — above all the subscription
token — or (c) read other sessions' data, all without stripping the session's
capabilities.

**Assets.** (1) the owner's subscription OAuth token (`~/.claude/.credentials.json`) —
must be UN-extractable by any session; (2) host integrity — no breakout, no using the box
to attack others, no resource-DoS of the bot; (3) other sessions' workdir + transcript
(invisible across sessions); (4) the bot's own secrets (`.env`: Telegram token,
allowlist).

**Adversary.** A code-level user the owner granted access to (semi-trusted → untrusted),
driving the agent and reading its output, plus the agent itself misbehaving.

**Non-goal.** Reducing capability — the agent still runs Bash/edits and reaches chosen
services.

**The exfil channels — close ALL or the asset leaks.** Token/data can leave a jail via:
(1) *filesystem* — host files (other sessions, `/root`, `.env`) → closed by the bwrap FS
confinement (§2: only the session's own workdir is mounted); (2) *network egress* → the
allowlist (§4); (3) *the bot's own output* — the agent `cat`s a secret and the bot streams
it back to the user (`Read` is auto-allowed) — **a firewall cannot close this**; (4) *an
allowed destination* — permitting GitHub turns GitHub into an exfil store. Channels (3)
and (4) prove the core point: **no egress control can protect a token that lives inside
the jail.** So the token must not be in the jail at all — which is exactly what the
credential broker (§3) guarantees: the real bearer stays host-side, the jail holds only a
placeholder, and channels (3)+(4) become moot — there is nothing to read, print, or POST.

**Why a domain proxy, not an IP allowlist (§4).** Anthropic's API is CDN-fronted: its IPs
rotate, and a single CDN range hosts thousands of unrelated sites. An *IP* allowlist is
therefore both fragile (constant refresh) and leaky (allowlisting the CDN range allows
every other site behind it — an exfil path). A *domain*-based filter (a CONNECT proxy that
tunnels TLS by the hostname in the CONNECT line, no MITM cert needed) is the stronger
boundary, and is paired with a hard cgroup-scoped egress block so the agent cannot ignore
`HTTPS_PROXY` and dial out directly — the proxy is the only exit.

**Why cgroup-scoped, never a global rule.** The jail runs `--unshare-user --uid 65534`, so
from the host kernel's view the egress socket's owner is the *outer* mapped uid (root) — a
per-uid `skuid` match won't fire. Egress is therefore filtered by **cgroup match**
(`iptables -m cgroup --path sbx`), which sidesteps the userns-uid problem and, critically,
scopes the rule to the jail only: a botched rule never locks the bot or the operator out
of the live VPS. The matching teardown (`egress-teardown.sh`) removes the jump + chain
cleanly. See §11 for the build traps this implies.

**Per-session secrets (§5).** Services that need auth (e.g. `git push`) take the **user's
own** credential via `/secret`, scoped to that one jail's HOME — the owner's creds never
enter any jail. A user leaking their own credential is their problem, not the owner's.

**Host integrity / DoS (§6).** Per-jail memory/CPU/pid caps plus an x86_64 syscall
denylist (seccomp) bound what a single session can consume or call (e.g. `ptrace` is
denied → no `strace`/`gdb` inside a code session).

> Historical note: this section preserves the original threat model and design
> rationale. The deliberated build options (proxy vs netns vs slirp) are settled — the
> deployment runs the CONNECT proxy + hard cgroup egress block described in §4.
