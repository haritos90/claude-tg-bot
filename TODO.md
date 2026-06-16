# TODO

Task ledger for this bot. Every task has a permanent numeric ID and flows
**Backlog → Open → Closed**, with a **Deferred** parking area at the very end.
This is the single place work is tracked; `AGENTS.md` points here.

## How this file works

**Lifecycle**

1. **New task** → add a row to **Backlog**, and (if the title isn't enough) a
   block under **Details** with the full description.
2. **Work starts** → move the row to **Open**.
3. **Finished** → move the row to **Closed**, fill the **Resolution** column (how
   it was resolved — or `Won't Do` / `Duplicate` for rejected tasks), and
   **delete its Details block**.
4. **Parked** → move the row to **Deferred** (end of file) and fill its
   **Reason** column. Deferred tasks keep their Details blocks; revive one by
   moving it back to Backlog/Open and dropping the Reason.

Detail blocks exist only for **Open + Backlog + Deferred** tasks. Closed tasks
are title-only history plus the **Resolution** note.

**Columns**

- **Pri** — `P0` critical (correctness / security / broken) · `P1` high ·
  `P2` medium · `P3` low / nice-to-have.
- **Eff** — `XS` ≤ 15 min · `S` ≤ 1 h · `M` ≤ ½ day · `L` ≤ 2 days · `XL` > 2 days.
- **Theme** — core · engine · security · isolation · ux · reliability ·
  observability · docs · build · tests · features.

**Sorting** — every table is kept in **ascending ID** order.

**Layout** — Open and Backlog first, then their **Details** blocks, then the
**Closed** history, then the **Deferred** table last.

**Table formats** — never delete a section's table when it empties; keep the
header rows. Columns:

- **Open** / **Backlog** — `| ID | Pri | Eff | Theme | Title |`
- **Closed** — `| ID | Theme | Title | Resolution |`
- **Deferred** — `| ID | Pri | Eff | Theme | Title | Reason |`

**Next free ID:** 160

---

## Open

Current, actionable work — promote from Backlog when picked up.

| ID | Pri | Eff | Theme | Title |
|---|---|---|---|---|
| — | — | — | — | _(empty — promote from Backlog when picking up new work)_ |

## Backlog

Not started; promote to Open when picked up.

| ID | Pri | Eff | Theme | Title |
|---|---|---|---|---|
| 119 | P1 | XL | security | Fully-contained sandbox (e2e): credential broker + egress allowlist + per-session isolation + DoS limits |
| 130 | P2 | M | security | Global memory: inject CLAUDE.md directly instead of `setting_sources=["user"]` (don't load settings.json permissions/env) |
| 134 | P2 | S | observability | `big_memory` 1M-context beta is IGNORED under the subscription (custom betas are API-key-only) — verify + document/rework |
| 135 | P2 | M | observability | Subscription usage shows just "5h OK" far from the limit — surface the real % used (Claude Code `/usage` shows e.g. 49%) via the account usage source the SDK rate-events don't expose |
| 141 | P1 | M | ux | Unify the two parallel `/settings` menus — retire the old flat `st:` hub, keep only the registry-driven scope-tabbed `sx:` hub (see menu.md §2.3) |
| 142 | P1 | S | ux | "Back" from settings sub-pages (Tools/Users/Usage) drops into the DEPRECATED old menu (`st:nav:main`/`admin`) instead of the new hub — the "another menu pops up" bug |
| 143 | P3 | XS | ux | Orphaned `/new` chat/code chooser: `on_new_cb` (`new:` callback) + `session.new_pick` i18n string are dead code |
| 144 | P2 | S | ux | A "Streaming" toggle resurfaces in the new `/settings` hub though `/stream` is retired (native streaming always-on) |
| 145 | P2 | M | ux | Inconsistent quick-command UX (#101): some setting commands open a picker, others only print text + require a typed arg |
| 146 | P2 | S | ux | Duplicate entry points / code paths per setting (language ×3, model & effort ×2) — consolidate on the hub picker |
| 147 | P2 | XS | ux | `/usage` display has no inline entry from the new hub (only the old Admin submenu or the typed command) |
| 148 | P2 | M | docs | `/help` text drifted from the command registry — generate it from `commands.COMMANDS` (group by `help_group`) |
| 149 | P3 | XS | docs | Session-creation model inconsistent across surfaces — `/new` vs `/newchat`/`/newcode` wording in `/help` + labels/docstrings |
| 150 | P3 | S | ux | Three names for one action: `/auto` = `/permissions full-access` = SDK `bypassPermissions` — make naming consistent |
| 151 | P1 | XL | features | Owner-configurable access model for every option/capability: per-setting global value + base access (Hidden/Read-only/Delegated) + per-user exceptions; effective values DERIVED per prompt, not stored (menu.md §4) |
| 152 | P2 | M | ux | Menu lifecycle/dismissal standard — menus must not linger in chat (edit-in-place / delete-on-close / move-to-bottom after posting content); audit all menus (menu.md §1.4) |
| 153 | P2 | S | ux | Argument-capture standard — no optional args; mandatory free-text args captured via the next message (+ /cancel), fixed-choice always a picker; audit all commands (menu.md §1.5) |
| 154 | P3 | S | ux | Unified emoji vocabulary — one emoji per concept across all surfaces; resolve collisions (🧠 model vs memory, 📦 sandbox vs export); align commands.py + i18n.py (menu.md §1.3) |
| 155 | P2 | S | ux | Frequency-ranked `/` command menu — register commands most-used first (Telegram surfaces only the top ~5 on mobile); keep the prominent set to ~3 (menu.md §1.6 / §2) |
| 156 | P2 | M | ux | Admin menu mirrors the user menu — owner sees the same menus with owner-only controls appended at the END of each menu, not a separate admin UI (menu.md §1.8) |

### Details

**#119 — fully-contained sandbox (e2e): credential broker + egress allowlist + per-session isolation + DoS limits** (P1 · XL · security · _supersedes #114 + #117_)

Umbrella design for a sandbox a semi-/untrusted **code**-level user can't use to
(a) break the server, (b) steal the owner's data incl. the **subscription
token**, or (c) read **other sessions'** data — **without stripping the session's
capabilities** (it keeps full tools + internet to chosen services; we contain
blast radius, not features). Analyse, then split into the sub-tasks at the end.

**Threat model.** _Assets:_ (1) the owner's subscription OAuth token
(`~/.claude/.credentials.json`) — must be UN-extractable by any session; (2) host
integrity — no breakout, no using the box to attack others, no resource-DoS of
the bot; (3) other sessions' workdir + transcript (invisible across sessions);
(4) the bot's own secrets (`.env`: Telegram token, allowlist). _Adversary:_ a
code-level user the owner granted access to (semi-trusted → untrusted), driving
the agent and seeing its output, plus the agent misbehaving. _NON-goal:_ reducing
capability — the agent should still run Bash/edits and reach chosen services.

**The exfil channels — close ALL or the asset leaks.** Data/token can leave via:
(1) _filesystem_ — host files (other sessions, `/root`, `.env`) → already closed
by the bwrap FS confinement (#104: only the session's own workdir is mounted);
(2) _network egress_ → the allowlist (component 2); (3) _the bot's own output_ —
the agent `cat`s a secret and the bot streams it to the user (`Read` is
auto-allowed) — **a firewall cannot close this**; (4) _an ALLOWED destination_ —
permitting GitHub turns GitHub into an exfil store. **Consequence:** (3)+(4) prove
**no egress control can protect a token that lives inside the jail** — so the
token must NOT be in the jail. This is the core, and the piece #114 was missing.

**Component 1 — credential broker (token leaves the jail; THE core fix).** The
subscription token stays OUTSIDE the jail in a small host broker process. `claude`
in the jail sends API traffic to the broker; the broker injects the real
subscription OAuth bearer and forwards to the real `api.anthropic.com`, streaming
the reply back. Inside the jail there is NO real token (at most a dummy the broker
overwrites) — so channels (3)+(4) become moot: nothing to read, print or POST.
The subscription is USABLE (via the broker) but UN-extractable.
- _Billing stays subscription (P0):_ the broker forwards the OAuth bearer from
  `~/.claude/.credentials.json`; it must NEVER inject `ANTHROPIC_API_KEY` /
  `ANTHROPIC_AUTH_TOKEN` (those flip to paid per-token billing). `ANTHROPIC_BASE_URL`
  is a route, not a key — P0-safe.
- _Two build variants (pick after recon):_ **(a) plaintext-to-broker** —
  `ANTHROPIC_BASE_URL=http://127.0.0.1:PORT`, broker does the real HTTPS; no MITM
  cert needed (simplest, IF claude honours BASE_URL under subscription auth + http).
  **(b) DNS-redirect + TLS-terminate** — point `api.anthropic.com` inside the jail
  at the broker; broker terminates TLS with a CA the jail trusts read-only, swaps
  the header, re-originates TLS (robust if BASE_URL isn't honoured).
- _OAuth refresh:_ access tokens expire; the broker owns refresh (refresh token →
  new access token), persisting new tokens host-side, never into the jail.

**Component 2 — egress allowlist (limit where the jail can reach; was #114).**
Even with no token in the jail, don't let the box reach arbitrary hosts (attack
relay) and DO enable chosen services (git/GitHub, package registries). Allow only
the broker + an allowlisted set of dev hosts; drop the rest. The session still
runs `claude` + its Bash tool as an unprivileged uid inside the bwrap jail. Keep
the mechanism in `deploy/` shell for distro portability; sandbox is **off by
default**, so a botched rule only affects sandboxed turns. Mechanism options A–E
(below) are this component's choices.

**Two gotchas that shape every option:**

- **CDN-IP churn + leak.** Anthropic's API is CDN-fronted: its IPs rotate and a
  whole CDN range may host thousands of other sites. So an *IP* allowlist is both
  fragile (needs constant refresh) **and leaky** (allowlisting the CDN's range
  effectively allows every other site behind that CDN — an exfil path). This is
  why a *domain*-based filter (a proxy) is stronger than an IP filter.
- **userns uid vs `nftables skuid`.** The jail uses `--unshare-user --uid 65534`.
  From the host kernel's view the egress socket's owner is the *outer* mapped uid
  (root), so an `nftables meta skuid 65534` match **won't fire**. Per-uid IP
  rules therefore need either a real-uid drop (re-architect the sandbox) **or** a
  **cgroup match** (`socket cgroupv2 …`) — put the jail in its own cgroup and
  filter on that, which sidesteps the uid problem cleanly.

**Options (pick one when reviving):**

- **A — CONNECT forward-proxy + domain allowlist (recommended core).** Run a tiny
  host proxy (tinyproxy/squid with an allowlist, or ~40 lines of Python/Go) that
  only permits `CONNECT api.anthropic.com:443` (+ allowed hosts). Give the jail
  `HTTPS_PROXY=http://<host>:<port>` via `--setenv`. A CONNECT proxy *tunnels*
  TLS (no MITM cert needed) and allowlists by the hostname in the CONNECT line —
  the agent can't reach `evil.com`. _Pros:_ domain-based (beats CDN churn),
  auditable/loggable. _Cons:_ a long-running component to manage; **must verify
  the `claude` CLI honours `HTTPS_PROXY`** (Node/undici usually does — confirm the
  streaming SSE call does too). _Catch:_ a proxy alone doesn't *force* its use —
  pair with a hard block (see E) so the agent can't ignore `HTTPS_PROXY` and dial
  out directly. Effort M.
- **B — nftables IP allowlist.** Resolve Anthropic IPs into an nftables set
  (refresh on a timer); `accept` to the set, `drop` the rest, scoped by **cgroup
  match** (per the gotcha above) or a real-uid drop. _Pros:_ no proxy, kernel-
  enforced. _Cons:_ hits the CDN-IP churn+leak problem head-on — fragile and
  potentially over-broad. Effort M (cgroup) / L (uid re-architecture).
- **C — `--unshare-net` + veth + host nftables/NAT.** Give the jail its own netns,
  wire a veth to the host, NAT + filter at the veth. _Pros:_ hardest boundary —
  you see every packet. _Cons:_ most plumbing (per-session veth create/teardown,
  IP alloc, forwarding, crash cleanup) and the most live-VPS risk; bwrap's netns
  is anonymous so the `ip link` dance is awkward. Effort L–XL.
- **D — `--unshare-net` + slirp4netns (userspace, unprivileged).** A userspace
  TCP/IP stack for the jail; restrict it / point it only at the A-proxy. _Pros:_
  no root nftables, unprivileged-friendly. _Cons:_ extra dependency + latency.
  Effort M–L.
- **E — A + a hard "proxy is the only exit" guarantee (the real production
  answer).** Combine A's domain filtering with a guarantee the proxy can't be
  bypassed: either nftables (cgroup match) dropping all jail egress except to the
  proxy's address, or `--unshare-net`+slirp routing solely to the proxy. Gets
  domain-based filtering **and** no bypass. Effort M–L.

**Cross-cutting must-dos when building:** (1) verify `claude` actually routes
through `HTTPS_PROXY` incl. the streaming connection; (2) **never write a global
firewall rule** — scope every rule to the jail's cgroup/uid or you risk locking
the bot/yourself out of the live VPS; (3) test matrix from inside the jail —
`curl https://api.anthropic.com` ✅, `curl https://example.com` ✗, a token-exfil
`POST` to an arbitrary host ✗, **and** a real `claude` turn still completes;
(4) keep all of it in `deploy/` shell, gated behind the existing `SANDBOX_CODE`
opt-in. **Recommendation: option E (A's proxy + a hard egress block).**

**Component 3 — per-session secret isolation (incl. user-supplied service creds).**
Each session's workdir + state (`.sbxstate`, #115) is already per-key and unmounted
from others — keep that invariant. For services needing auth (e.g. `git push`), the
USER supplies THEIR OWN credential, scoped to that session only (a `/secret`-style
command writing into that session's jail HOME) — the owner's creds NEVER enter any
jail. A user leaking their own credential is their problem, not the owner's.

**Component 4 — host integrity / DoS.** Process cap shipped (#116, `ulimit -u`).
Add per-session cgroup memory + CPU limits (a systemd scope) and a seccomp profile
to shrink the kernel attack surface (also lowers the residual userns/kernel-escape
risk — bwrap is not a VM, so keep the host kernel patched). _#117's workdir-noexec
is REJECTED here: it is capability-reduction (counter to the non-goal) and weak
anyway — interpreters (`python`/`sh`) run scripts regardless, and bwrap 0.8 has no
per-bind noexec. Recorded so it isn't re-proposed._

**Component 5 — all OS/network mechanism in `deploy/` shell.** Broker + proxy +
firewall wiring as shell/standalone scripts under `deploy/` (Python only sets env
+ lifecycle), per the distro-portability rule; all gated behind `SANDBOX_CODE`.

**Component interaction (so the pieces fit).** The broker listens on host loopback;
the egress mechanism must keep it reachable. Simplest combination: **shared netns +
cgroup-nftables** (loopback broker stays reachable, egress filtered by cgroup);
`--unshare-net`+slirp would instead route the broker via the slirp gateway. Decide
together with component 2.

**Recon FIRST (cheap, ZERO token risk — decides feasibility + variant).** (1) Does
`claude` route through `ANTHROPIC_BASE_URL` / `HTTPS_PROXY` under SUBSCRIPTION auth,
and start with a dummy credential? → picks broker variant (a) vs (b). (2) Capture
the exact headers `claude` sends to `api.anthropic.com` (point it at a logging proxy
ON THE HOST with the real token — token never leaves the host) so the broker can
reproduce auth + any `anthropic-beta` OAuth headers + the refresh flow.

**Maps to the 3 goals.** _break the server_ → FS confinement (#104) + egress
allowlist + DoS limits (#116 + cgroup/seccomp) + patched kernel. _steal my
data/token_ → credential broker (token not in jail; closes FS + network +
chat-output at once) + FS confinement keeps `.env` out. _steal other sessions'
data_ → per-session workdir/state binds (#115), no cross-session mounts.

**Suggested task split.** 119a recon (claude base-url/proxy + dummy-cred + header
capture) · 119b credential broker + OAuth refresh (`deploy/`) · 119c egress
allowlist (CONNECT proxy + cgroup-nftables hard block) · 119d per-session
user-supplied service creds (`/secret`) · 119e DoS hardening (cgroup mem/CPU +
seccomp).

**#130 — global memory: inject CLAUDE.md directly, not via `setting_sources=["user"]`** (P2 · M · security)

The #121 audit found that per-user GLOBAL MEMORY (#122) loads the `"user"` source,
which pulls in `~/.claude/settings.json` — not just CLAUDE.md/memory. That settings
file can carry `permissions.allow` rules (auto-allow tools the bot deliberately keeps
OUT of `allowed_tools`, bypassing the `can_use_tool` gate) and an `env` block (a
settings `ANTHROPIC_API_KEY` survives `engine._build_env`'s pop and can flip a user's
turns to paid billing — the #1 hard rule). Owner-gated + OFF by default + the owner's
settings.json has none today, so no active leak — but the blast radius exceeds the
"reads your ~/.claude" framing.

Fix: stop widening `setting_sources`. When `global_memory` is on, READ the owner's
memory files (`~/.claude/CLAUDE.md` + the memory dir) and inject their content
directly — chat: append to the system prompt; code: via an additive system-prompt
preset — keeping `setting_sources=[]` so settings.json (permissions/env) is never
loaded. Verify the memory actually reaches the model in both modes. Until then:
trusted users only; the card + AGENTS/engine document the caveat.

**#134 — big_memory 1M beta ignored under subscription** (P2 · S · observability)

The CLI logs "Custom betas are only available for API key users. Ignoring provided
betas" — so `betas=["context-1m-2025-08-07"]` (engine; passed for code always + chat
when big_memory) is a NO-OP under the OAuth subscription. So `big_memory`'s 1M-window
promise (#32/#54) is inactive today; only its durable-resume half still works. Verify
whether 1M is reachable another way under subscription; otherwise relabel big_memory
as "durable context" only (drop the 1M claim in `/status`, help, AGENTS, README) so it
isn't misleading.

**#141 — unify the two parallel `/settings` menus** (P1 · M · ux)

`/settings` opens the registry-driven scope-tabbed hub (`sx:`, `_send_ss_hub` /
`on_settings_v2_cb`, `settings_schema.py`), but the OLD flat hub (`st:`,
`_settings_keyboard` / `on_settings_cb`) was never retired. Its `main`/`model`/
`effort`/`perm`/`lang` pages are dead code (no entry point) yet still fully built;
its `tools`/`users`/`admin`/`usage` pages are STILL live (the new hub links to
`st:nav:tools` / `st:nav:users`). One parameter → two differently-styled menus.
Fix: keep only the `sx:` hub; port Tools / Usage / Users onto it as sub-pages with
Back → the hub (see #142); delete the dead `_settings_keyboard` pages + their i18n
(`settings.header`, `settings.perm_seg`, `_settings_text`). See `menu.md` §2.3 /
§4.1–4.2.

**#142 — Back from settings sub-pages drops into the DEPRECATED old menu** (P1 · S · ux)

The literal "another menu pops up". New hub → «🧰 Tools» (`st:nav:tools`) → «Назад»
= `st:nav:main` → the OLD flat settings page. Same via «👥 Users»
(`st:nav:users`) → «◂ Settings» = `st:nav:admin` → old Admin → Back = `st:nav:main`.
Fix the back targets in `_settings_keyboard` (tools/users/admin/usage) +
`_users_keyboard` to re-open `_send_ss_hub` instead of `st:nav:main` / `st:nav:admin`.
Quick win even before the full unification (#141).

**#143 — orphaned `/new` chat/code chooser** (P3 · XS · ux)

`on_new_cb` (callback `new:`) + the i18n string `session.new_pick` are dead: since
#133 `/new` always creates a chat (no chooser), and the `/sessions` browser emits
`ses:new:chat` / `ses:new:code` (handled by `on_sessions_cb`), not `new:`. Nothing
emits `new:`. Remove `on_new_cb` + `session.new_pick` (comment-out per convention),
or rewire if a chooser is actually wanted.

**#144 — Streaming toggle resurfaces in the new hub** (P2 · S · ux)

`stream_enabled` is in `settings_schema.SETTINGS` + `PAGE_ORDER` with
`view_role=CHAT`, so the new `/settings` hub renders a «Streaming: on/off» toggle —
even though `/stream` was retired (native streaming always-on) and the old menu's
streaming row was deliberately commented out (`_settings_keyboard`). Decide: drop
`stream_enabled` from the registry/PAGE_ORDER (recommended), or truly re-enable
`/stream`. menu.md ❓DECISION 2.3-a.

**#145 — inconsistent quick-command UX (#101 convention)** (P2 · M · ux)

Fixed-choice setting commands should ALL open an inline picker. Today only
`/model`, `/effort`, `/language` do (pickers `pm:` / `pe:` / `lang:`);
`/permissions`, `/usage`, `/memory`, `/maxturns`, `/sandbox`, `/auto` only print
text and require a typed argument. Make them consistent: no-arg → open the matching
`/settings` row picker; with-arg → apply directly. menu.md ❓DECISION 2.3-b.

**#146 — duplicate entry points / code paths per setting** (P2 · S · ux)

Same value reachable via several distinct callbacks: language = `/language`
(`lang:`) + old `st:set:lang` + new `sx:…:language` (3 paths); model & effort =
standalone `pm:` / `pe:` pickers + new hub (2 paths). Consolidate: the slash
commands become thin entry points that open the corresponding hub row picker
(depends on #141). Removes drift between paths.

**#147 — `/usage` display has no inline entry from the new hub** (P2 · XS · ux)

The usage-mode picker (off/footer/pinned/both) lives only in the old
`st:nav:admin → st:nav:usage` submenu, unreachable from the `sx:` hub — so only the
typed `/usage <mode>` works inline. Add a «📊 Usage display» row to the hub
(owner-only), folding usage into the unified settings (part of #141).

**#148 — `/help` drifted from the command registry** (P2 · M · docs)

`i18n.help.text` is hand-maintained and out of sync with `commands.COMMANDS`: it
foregrounds `/newchat` / `/newcode` / `/reset` and omits many live commands
(`/effort`, `/maxturns`, `/fork`, `/recap`, `/history`, `/export`, `/tools`,
`/sandbox`, `/level`, `/expire`, `/limit`). Generate `/help` from the registry
(group by `Cmd.help_group`, EN+RU from `Cmd.label`) so help can't diverge from the
menu. The startup consistency check only catches REMOVED commands lingering, not
missing coverage.

**#149 — session-creation model inconsistent across surfaces** (P3 · XS · docs)

The `/`-menu + `commands.py` say `/new` is the way (born chat, upgrade via `/code`,
#133), but `/help` and the `cmd_newchat` / `cmd_newcode` docstrings still present
the old immutable-type model ("type is fixed for the session's life"). Align the
wording (help text, docstrings, labels). Pairs with #148.

**#150 — three names for "run tools without asking"** (P3 · S · ux)

`/auto on` = `/permissions full-access` = SDK `bypassPermissions` — three surfaces,
one concept. Pick a single canonical name and make `/auto`, `/permissions`, and the
settings `permission_mode` row present it consistently (e.g. `/auto` documented
everywhere as just a shortcut for the full-access policy).

**#151 — owner-configurable, derived access model for every option/capability** (P1 · XL · features)

The centerpiece (full spec in `menu.md` §4). Replace the bespoke, per-command
access logic (owner-only checks, code-level checks, `may_max_effort`,
`full_access_owner_only`, per-user tool caps, …) with ONE uniform mechanism that
governs both setting VALUES (model, effort, permission_mode, max_turns, big_memory,
language, tools, …) and gated CAPABILITIES (use code mode, use `max` effort, use
`full-access`, use a given tool). Each option is one row in a master matrix.

Model (menu.md §4.1–4.6). The owner controls three things per option: (1) the
**global value** (default + live value for anyone who hasn't overridden it),
(2) the **base access level** — *Hidden* / *Read-only* / *Delegated*, (3) a
**per-user exceptions** list (who differs from the base). Fixed rules for all
options: value resolution **session → user-default → global**; owner never sets a
user's value or a session's value (if delegated, the user owns the value); **soft
revoke** (lowering access keeps but stops counting the user's stored values, so
the effective value falls back to global; restoring brings them back — nothing is
deleted); a delegated option starts on live global until the user sets their own
(optionally snapshot global into the user default at delegation for isolation).

Implementation shape. Make effective values **DERIVED, not stored**: compute on
each prompt from the matrix — base access + exceptions for this user, then
global → user default → per-session override (keyed by session id). Persist only:
(a) the owner's global values + access levels + exceptions, (b) each user's
personal defaults, (c) each session's explicit overrides. Do **not** persist a
per-session "actual value", so any owner change applies from the user's very next
prompt with no migration/refresh. Storage: a global-config table + a per-user
overrides/exceptions table + the existing per-session override columns, addressed
by session id. Resource quotas (token caps, expiry) stay a SEPARATE owner-only
axis (limits, not values) on the user card — out of this matrix.

Builds on / supersedes the settings work: depends on #141 (single hub) and #146
(one path per setting); generalizes `settings_schema.py` (Scope/Role → the
3-level access + exceptions) and the per-user admin (#120) into the exceptions
layer. Split when picking up: 151a data model + resolver (derived `effective(user,
session, option)`), 151b owner UI to set base-access + exceptions per option,
151c migrate each existing gate onto it, 151d remove the bespoke checks.

**#152 — menu lifecycle / dismissal standard** (P2 · M · ux)

Menus currently linger in the chat history (stale keyboards scroll up). Standard
(menu.md §1.4): navigation edits the SAME message; applying a value edits in place
+ toast; Close deletes the message (fallback: edit to a "closed" line, no live
keyboard left); an action that posts content re-posts the menu at the bottom and
deletes the previous one; exactly one live menu per surface. Audit settings,
sessions, pickers, queue, user cards. Broader than the specific back-target bug
(#142).

**#153 — argument-capture standard (no optional args)** (P2 · S · ux)

Telegram sends a tapped command immediately and use is mobile-first, so a command
must be either argument-free or take a MANDATORY arg captured via the next message
(prompt + `/cancel`); fixed-choice input is always a picker, never typed; no
command relies on inline optional args or errors with a "usage:" line on empty
input (menu.md §1.5). Audit every command and align (related to #145, which is the
picker half).

**#154 — unified emoji vocabulary** (P3 · S · ux)

Adopt one emoji per concept across all surfaces (menu.md §1.3). Resolve current
collisions: 🧠 is used for BOTH model (`settings.row_model`) and memory
(`usercard.btn_memory`) — reserve 🧠 for model, use 🗄 for memory/context; 📦 is
used for BOTH sandbox (`settings.row_sandbox`) and file export — reserve 📦 for
export, 🧪 for sandbox. Align labels in `commands.py` + `i18n.py`.

**#155 — frequency-ranked `/` command menu** (P2 · S · ux)

Telegram's command menu is only practical for the first few entries on mobile, so
register commands in usage-frequency order (most-used first) and keep the prominent
set to ~3 (the everyday trio `/new`, `/sessions`, `/settings` at the very top); the
rest stay typeable + reachable via inline menus (menu.md §1.6, ranking in §2).
Reorder the `commands.COMMANDS` registry accordingly (it already drives
`setup_commands`).

**#156 — admin menu mirrors the user menu** (P2 · M · ux)

The owner should see the SAME menus as users, with owner-only controls appended at
the END of each menu (the `🌍 Global` tab + owner rows in settings; owner buttons
as the last rows above Close), not a separate admin surface (menu.md §1.8). Audit
the settings hub, user cards, and any owner-gated menu so admin features read as an
extension of the user menu, consistently positioned at the bottom.

---

## Closed

Title-only history.

| ID | Theme | Title | Resolution | Release notes |
|---|---|---|---|---|
| 1 | core | aiogram long-polling skeleton, owner allowlist, SQLite per-thread state, topic-as-session routing | Delivered: `bot.py` long polling, `access.AllowlistMiddleware`, `db.py` per-thread SQLite, `handlers.thread_key` routing (0 = General). Running. | |
| 2 | engine | chat + code modes via Agent SDK on the subscription; per-thread isolation | Delivered in `engine.py`: `ClaudeSession`, `setting_sources=[]`, API-key-stripped child env, own cwd + `resume`; verified subscription-only (no API key). | |
| 3 | ux | Claude-Code-style streaming — write-head + tool-status | `streamer.py` rewritten to a typewriter write-head: `update()` buffers text, a frame loop reveals it progressively and slides a rotating braille caret to the frontier (runs while buffered, spins in place when caught up / before the first token). Live tool-status, chunked/`.md` flush. Evaluated native `sendMessageDraft` — private-chat-only (`TEXTDRAFT_PEER_INVALID` in groups), unusable in the supergroup; write-head kept. See AGENTS §5 + #39. | |
| 4 | security | permission gate: inline Allow/Deny for dangerous tools in code mode | Delivered: `permissions.PermissionGate` inline Allow/Deny; `SAFE_TOOLS` auto-allowed; dangerous tools gated via `can_use_tool`. (Owner-only approval split out as #30.) | |
| 5 | observability | `/status` surfaces token usage, cache-window timer, subscription rate-limit | Delivered: `cmd_status` shows mode/model/dir, busy/queue, 5-min cache window, subscription windows, and lifetime token totals. | |
| 6 | ux | task chaining — queue follow-ups to reuse context + cache | Delivered: per-thread `asyncio.Queue` drained serially in the SAME session (`sessions._worker`), preserving context + prompt cache. | |
| 7 | docs | README first-time Telegram setup + "no Premium needed" | Delivered: README covers BotFather, supergroup + Topics, Manage Topics, `OWNER_ID`, and that Telegram Premium is not required. | |
| 8 | build | choose and add a LICENSE | Added MIT `LICENSE`, `Copyright (c) 2026 haritos90`. | |
| 9 | build | GitHub Actions CI | Added `.github/workflows/ci.yml`: ruff + `py_compile` + import smoke on push/PR to `main` | |
| 10 | reliability | systemd unit hardening (Restart=always, resource limits, basic sandboxing) | Hardened `deploy/tg-bot.service`: `ProtectSystem=strict` + `ReadWritePaths` (workdir, db, `~/.claude`), `PrivateTmp`, `MemoryMax`, `NoNewPrivileges`; added the REQUIRED `HOME`/`PATH` env so the `claude` CLI is found + creds reachable under systemd. The host install (`/etc/systemd/system`) is run by the owner. | |
| 17 | build | create the private GitHub repo `claude-tg-bot` | Owner created the private repo and pushed it via `gh` (done 2026-06-14). | |
| 19 | ux | terminal-faithful rendering with copyable `<pre>` code blocks | Delivered: `markup.md_to_html` emits `<pre>` for one-tap copy and `<pre><code class="language-x">` for fenced blocks with a language (label + highlighting); raw-split-then-render keeps every chunk's tags balanced (`split_markdown`). | |
| 20 | security | multi-user allowlist from a gitignored `allowlist.json` | Delivered: `allowlist.py` JSON store (gitignored), fail-closed, owner always allowed, username→id pin on first contact; `/allow` `/deny` `/users` owner-only. | |
| 21 | observability | ambient subscription-usage display (`/usage off\|footer\|pinned\|both`) | Delivered: `/usage` modes via `usage.py`; per-window % left; persisted across restart (`db.kv` `rate_snapshot` + pinned msg id). | |
| 22 | ux | v1 command palette + `setMyCommands` menu | Delivered: `BOT_COMMANDS` + `setup_commands`; `/permissions` maps `ask\|auto-edits\|plan\|yolo` → SDK `permission_mode`. | |
| 24 | engine | chat mode was not tool-free (model used WebSearch in chat) | Set `tools=[]` for chat (not `None`); `None` left the CLI default tools on. See AGENTS.md §5 | |
| 25 | ux | command replies showed literal `<b>` / `&lt;` (e.g. `/help`) | `handlers.reply` no longer double-escapes: command HTML is sent as-is, `md_to_html` is only for model output | |
| 26 | observability | usage footer showed `5h (n/a)` | `usage.window_str` shows the window status (`OK`/`⚠ high`/`⛔ limited`) when `utilization` is null; `%` shown only when the API sends it | |
| 27 | features | implement /context /stream /verbose /rename /close /queue /clearqueue /retry | Shipped from #23: `/context` via `get_context_usage`; `/stream` + `/verbose` in-memory per-thread flags; `/rename` + `/close` via `edit_forum_topic`/`close_forum_topic`; `/queue` + `/clearqueue` manage the chaining queue; `/retry` re-runs the last prompt | |
| 29 | reliability | changing /mode·/model·/cwd·/permissions mid-run broke the in-flight turn | `_get_session` never aclose()s/rebuilds while a worker is busy — it returns the live session and defers the rebuild to the next idle message; `on_mode_or_model_or_cwd_change` defers + returns a flag so the handler appends "(applies after the current run finishes)". Functionally tested. | |
| 30 | security | tool-approval taps were not owner-restricted | `on_perm_callback` ignores non-owner taps ("Only the owner can approve tools."); only the owner authorizes Bash/Write/Edit in code mode. | |
| 31 | security | code-mode blast radius for non-owners | `/cwd` sandboxed under `BASE_WORKDIR` for non-owners (absolute paths + `../` escapes rejected via `relative_to`); `/permissions yolo` is owner-only. Owner unrestricted. | |
| 33 | observability | verify the SDK usage-dict keys feeding `db.add_usage` | Verified: `ResultMessage.usage = data["usage"]` is the raw Anthropic API `usage` object (snake_case `input_tokens`/`output_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`) — keys match; added a sync-keeping comment in `db.py`. | |
| 34 | ux | `/reset` while busy emitted a redundant "⏹ Execution stopped." | Removed the worker's cancel-path `_notify` — graceful `/stop` interrupts (never cancels), so the worker is only cancelled by `reset()`/shutdown, both of which already report. | |
| 35 | ux | graceful `/stop` could surface a spurious error status line | engine sets `_interrupted` in `interrupt()`; `run()` returns quietly on an exception while interrupted, so the streamed partial stands as the final answer (real failures still surface). Functionally tested. | |
| 36 | observability | pinned-usage edit + rate DB write fired on every rate event | `_run_one` persists + edits only when `_rate_signature()` changes, skipping repeated identical rate events. | |
| 37 | features | file attachments (images, PDF, text/code) | Telegram photos, image files, PDFs, and UTF-8 text/code files are accepted: images/PDFs go to the model as Anthropic content blocks (image / `document`), text files are inlined into the prompt; caption = prompt; works in chat AND code mode. Generic `attachments` plumbing (engine `_send_query` → sessions queue → `run`). Caps: 5 MB image / 20 MB PDF / 1 MB text. Verified live with real image + PDF calls + plumbing tests. Albums arrive as separate turns (one per message). | |
| 38 | ux | Claude-Code-style token counts in /status + /context | `_fmt_tokens` abbreviates counts (12345 → "12.3k", 1.2M); `/status` shows `Tokens: Xk in · Yk out` + `Cache: …`, `/context` abbreviates used/total — easier to read than raw digits. | |
| 39 | observability | evaluate native Telegram streaming (sendMessageDraft) | Investigated per owner request: real + aiogram-supported (`bot.send_message_draft`, Bot API 9.3+, opened to all bots in 9.5), but tested live → **private-chat-only** (`TEXTDRAFT_PEER_INVALID` for supergroup/topics). Incompatible with the Topics-as-sessions design; kept the write-head (#3). Documented in AGENTS §5. | |
| 32 | features | `/memory on\|off` per-topic big memory | New `big_memory` flag + `chat_session_id` column (live `bot.db` migrated). On → chat gets the 1M context beta and resumes its persisted session, so the topic survives restart + `/stop`; off → standard ephemeral chat. Chat session id is ALWAYS persisted (so toggling on keeps the context built so far) but only RESUMED when on; `/reset` clears it. `/status` shows the state. Verified end-to-end. | |
| 40 | ux | caret zoo + comfortable speed | 17 caret styles (dots, snake, slashes, glitch glyphs, moon, clock, Pac-Man fwd/back, runner, …) chosen at RANDOM per turn (the signature flourish); text reveal slowed to ~16 chars/sec (was too fast); speed presets calm/normal/fast; style + speed persisted and pickable in `/settings`. | |
| 41 | ux | settings menu (`/settings`) + trimmed palette | Inline tap-to-change menu: mode, model, permissions, usage, streaming, verbose, big memory, caret style + speed (✓ marks current, sub-pages, yolo owner-only). `/` palette trimmed to 8 essentials; everything else still works when typed. | |
| 42 | ux | arg-capture for free-text commands | `/new` and `/rename` with no argument PROMPT and capture the user's NEXT message as the argument (Telegram sends a picked command immediately); `/cancel` aborts. | |
| 43 | engine | math rendered as raw LaTeX in chat | Chat system prompt now tells the model Telegram cannot render LaTeX — write plain Unicode (×, ≈, ², √, …), no `$…$` / `\frac` / `\text`. Robust render-time conversion tracked as #51. | |
| 44 | core | DM mode foundation (private chat, isolated) | Private chats route to bot-managed sessions with synthetic NEGATIVE keys that never collide with supergroup topics (≥ 0) or other users; per-user current-session pointer; gate re-keyed by the unique session key; DM-aware `/start`; `/new` creates a DM session; `/sessions` browse/search/switch + info card. Isolation verified. | |
| 45 | features | DM smooth generation: native `sendMessageDraft` streaming | DM streams via `send_message_draft` (`streamer._render_draft`): Telegram animates appended chars letter-by-letter. Text-only (no status block / caret) to keep a clean growing prefix; `draft_id` constant; ≤5 updates/sec (`_DRAFT_INTERVAL=0.2`, measured 3s RetryAfter penalty below ~110ms); `finish()` persists a real message; no fallback to write-head on transient errors. Verified live by the owner. | |
| 46 | docs | document DM-first overhaul | AGENTS.md reframed to DM-first (intro + §5 streaming/resume/permissions), `streamer.py` row updated; README/CLAUDE refreshed; this TODO updated. | |
| 50 | ux | per-session working directory by id | Default cwd is now `BASE_WORKDIR/<session_key>` (set in `allocate_dm_session` + `_ensure_state`); the engine `os.makedirs` it before a code turn (fixed "Working directory does not exist"). | |
| 52 | ux | `/rename` for DM sessions | `/rename <name>` (or arg-capture) renames the current DM session via `db.set_session_name`; group path still renames the forum topic. | |
| 53 | engine | session mode bound at creation (chat XOR code) | A session's type is FIXED at `/new chat\|code`; `/mode` is read-only (no mutation — it used to corrupt a chat session into code); mode toggle removed from `/settings`. `allocate_dm_session` takes `mode`. | |
| 54 | engine | durable context by default | Chat sessions always resume `chat_session_id` across restart/`/stop` (decoupled from `big_memory`, which is now only the 1M-window toggle). Owner confirmed context returns after a restart. | |
| 55 | security | code-mode auto-approve actually works | The gate (`permissions.make_callback`) now enforces `permission_mode`: `bypassPermissions` (`/auto on`, owner-only) auto-allows everything, `acceptEdits` auto-allows file edits. Before, `can_use_tool` prompted regardless of the SDK mode. | |
| 56 | ux | code-mode output split into messages | `streamer.segment_break()` commits each burst of model text (between tool calls) as its own message so progress is visible; the SDK `result` is not re-shown when segmented. | |
| 57 | ux | silent intermediates + no link previews | Streaming/segment messages are silent (`disable_notification`); only the final answer pings; permission prompts still notify. All sends/edits pass `_NO_PREVIEW` (links never expand). | |
| 58 | ux | delete DM sessions | 🗑 in `/sessions` → confirm → `sessions.reset` (close subprocess) + `db.delete_dm_session` + remove the workdir + fix the current pointer. Scoped to the user's own negative keys. | |
| 59 | ux | retire the caret + tool-status machinery | Caret zoo, `_spinner`, status block, `/settings` caret+speed pages removed (Telegram owns the DM frontier; the caret just flickered). Single streaming standard. **(2026-06-14 audit follow-up:** removed the leftover dead `SessionManager.set_caret_speed` + its `caret_speed` kv-load + the now-unused `CARET_SPEEDS` import in `sessions.py`; the dormant group write-head keeps a fixed `"normal"` pace. The gap the re-audit flagged is closed.) | |
| 60 | ux | retire the dead `/verbose` command + plumbing | Removed the `/verbose` handler, `set_verbose`, the `verbose` status-dict key, the `/settings` verbose row, and the `/verbose` menu entry — zero `verbose` references remain in any `.py`. (The previous session completed the code removal but died before closing this + restarting; verified complete + closed 2026-06-14.) | |
| 61 | ux | discoverable session creation + full command menu + chat/code style separation | `/newchat` + `/newcode` create immutable-typed sessions in one tap; bare `/new` shows a 💬/⌨️ chooser (`on_new_cb`). `setMyCommands` rebuilt most-used-first with **all** 20 user commands (incl. `/rename`), plus an owner-only chat-scoped menu (`auto`/`allow`/`deny`/`users`) via `BotCommandScopeChat`. Mode glyph (💬/⌨️) + a one-line `mode_tagline` now lead every session surface — creation, switch card, `/status`, `/mode`, `/sessions`. Verified: router builds, all commands register, real DB create path makes distinct chat/code sessions. | |
| 11 | ux | code snippets weren't copyable (the real ask behind "telegramify backend") | Root cause (diagnosed by sending the owner a live A/B/C test message): the client copies only the tapped token, never a whole `<pre>` block. Fix: render each fenced code block as its **own message** (`markup.segment_blocks` + `streamer._render_message_chunks`) so long-press → Copy grabs the whole snippet. Also added `~~~` fence support. `telegramify-markdown` NOT adopted — the hand-rolled HTML renderer (copyable `<pre>`, language labels, fence-safe splitting) is better-controlled; closing the dep as won't-do. | |
| 12 | tests | unit tests for `markup` split/escape + the `db` layer | Added `tests/` (18 tests, pure `pytest` — async tests wrap `asyncio.run`, no pytest-asyncio needed) covering escape, split round-trip, fence repair, `segment_blocks`, LaTeX conversion + prose/code protection, and the db layer (allocate/get, `/stream` persist, message log, rate history, pro-options, scoped delete). `requirements-dev.txt` + a `pytest -q` CI step + root `conftest.py`. | |
| 13 | ux | `/queue` per-item cancel | Queue items carry a per-thread monotonic `qid`; `/queue` lists each pending prompt with a ✖ Cancel button (+ Clear all), `on_queue_cb` → `sessions.cancel_queued(thread_id, qid)` rebuilds the queue minus that id under `rec.lock` (order preserved). Tested. | |
| 14 | ux | `/new` deep-link confirm | **Won't Do** — DM-first: a DM session is a synthetic negative key, not a forum topic, so there is no `t.me/c/…` deep-link target. `/sessions` switch + the creation/switch cards already provide navigation; the deep link is only meaningful for the frozen supergroup mode. | |
| 15 | observability | per-window rate-limit history trend in `/status` | `rate_history` table (append-only, trimmed to 500) written on each rate-signature change; `/status` shows a small `_sparkline` of utilization per window (5h/7d) when ≥2 numeric points exist (utilization is often null far from a limit, so the trend appears only when meaningful). | |
| 16 | features | voice-note input | **Deferred** — not supported by the SDK: there is no subscription-safe STT (no API key allowed; chat mode is tool-free), so transcription would need a heavy local model. Parked pending a chosen STT backend (see Deferred). | |
| 23 | features | "Pro" command layer — safe subset | Shipped the SDK-clean subset (per a 2026-06-14 SDK introspection): `/effort` (`effort`), `/maxturns` (`max_turns`), `/dirs` (`add_dirs`, code, sandboxed for non-owners), `/fork` (`resume` + one-shot `fork_session`, branch id persisted then flag cleared). Persisted as `threads` columns; a change rebuilds the session (same busy-guard as `/model`). Remainder (`/rewind`, `/resume`, `/mcp`, `/budget`, `/continue`) deferred — see Deferred #62. | |
| 28 | ux | persist the per-session `/stream` flag | Added a `stream_enabled` `threads` column; `set_stream` persists it and `_get_session` restores it into the record on (re)build — survives restart. | |
| 47 | features | `/history` (export transcript) + `/recap` (last exchange) | Added a `messages` table; `sessions._run_one` logs the user prompt + assistant reply each turn (cleared by `/reset` and session delete). `/recap` shows the last exchange; `/history` exports the full transcript as a `.md` document. | |
| 49 | ux | inline ⏹ Stop button | Worked around the draft/`reply_markup` limitation with a SEPARATE control message: the streamer posts a ⏹ Stop message only once a turn outlasts `_CONTROL_DELAY` (3s, so quick replies don't flicker) and removes it when the turn ends; `on_stop_cb` → `sessions.stop` (graceful). | |
| 51 | ux | render-time LaTeX→Unicode | `markup._latex_to_unicode` runs inside `md_to_html` AFTER code is stashed (so code spans/blocks are never touched): converts `\frac`/`\sqrt`/`\times`/greek/arrows, `^{}`/`_{}` scripts, and strips `$…$`/`\(…\)` math delimiters — guarded so prose like "$5 and $10", `_italic_`, and `a_b` are preserved. Tested. | |
| 63 | features | localize the bot UI (Russian) + per-user language selection | New `i18n.py` extensible l10n table (rows = keys, cols = languages; `en` canonical, `ru` translation; `t()` falls back en→key, gracefully ignores bad format args; `onoff`/`yesno`/`mode_word` helpers; `lang` is positional-only so a `{lang}`-style placeholder can't collide). Every user-facing string across `handlers.py`/`permissions.py`/`usage.py`/`sessions.py`/`streamer.py`/`engine.py` routes through `t()` with the acting user's locale; engine error events carry a stable `error_key` localized at the consumer. Per-user locale auto-detected from the Telegram `language_code` by a new `access.LanguageMiddleware`, cached in `i18n`, persisted in `db` (`kv` `lang:<uid>`), overridable via `/language` (+ a 🌐 `/settings` row). `setMyCommands` registered per locale (incl. owner scope). Scope is UI only — Claude's output is untouched; comments/docstrings/docs stay English. Adversarial multi-agent audit run; all findings fixed. `tests/test_i18n.py` (13 tests) enforces en/ru placeholder + HTML-tag parity and render-without-crash; ruff + 31 tests green; verified live (RU command menu registered with Telegram). | |
| 64 | reliability | graceful shutdown never tore down live sessions | `bot.py` `main()` `finally` now `await sessions.aclose()` BEFORE `close_db()`, so live `claude` subprocesses disconnect, workers cancel, and best-effort writes aren't aimed at a closed DB. Verified (import + tests). | |
| 65 | security | global usage-mode / draft-streaming writable by any non-owner | Owner-gated the mutations: `/usage <mode>` rejects non-owners (`common.owner_only_usage`); the settings `usage` + `drafts` rows are hidden for guests and `_settings_apply` ignores their taps. `/stream` stays per-session. | |
| 66 | reliability | rendered HTML chunk could exceed 4096 → silently dropped | Added `markup.render_within_limit` (+ `HARD_LIMIT=4096`): renders each raw chunk and re-splits the RAW source when the HTML overflows (never splitting rendered HTML), with a hard-cut floor; `streamer._render_chunks`/`_render_message_chunks` use it, footer gate moved to `HARD_LIMIT`. Test added. | |
| 67 | docs | README described the FROZEN supergroup/Topics flow as the architecture | Rewrote the "How it works" diagram + "Part A" setup around DM → `/new` → isolated session; fixed the Commands table (added `/newchat`·`/newcode`·`/sessions`·`/rename`·`/history`·`/recap`·`/settings`; `/mode` marked read-only; `/usage`·`/auto` marked owner); replaced remaining "topic"/"group" wording with "session"/DM. | |
| 71 | ux | `/recap` + `/history` empty-state misled when the model still had context | The empty branch now checks for a persisted `code_session_id`/`chat_session_id` and shows `recap.empty_has_context` ("older/resumed context isn't in the transcript; new messages are saved from now on") instead of "no conversation logged." en+ru added. | |
| 72 | ux | `/sessions` name + 🗑 were equal-width | Redesigned the DM row: the session name is a full-width button over a compact controls row (favorite + 🗑), so the name reads cleanly and the trash is a small half-width control (Telegram forces equal width + centered text within a row). | |
| 74 | build | thin `.gitignore` | Expanded to a full Python block (`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`.coverage`/`htmlcov`/`.tox`/`.eggs`/`*.egg`), cross-platform OS + editor sections, and `.env` + `.env.*` with `!.env.example`; kept `CLAUDE.md`/`.claude/` + secret/runtime entries. | |
| 85 | security | no `SECURITY.md` | Added a security policy: private disclosure via GitHub advisory, what to include + redact, Scope, and In/Out-of-scope tailored to this bot (token/allowlist/session leakage, permission-gate bypass, `/cwd`+`/dirs` escape, allowlist-fail-open, `ANTHROPIC_API_KEY` paid-billing, isolation; upstream SDK/host out of scope). | |
| 86 | docs | no `CONTRIBUTING.md` | Added a contributor guide distilling the AGENTS golden rules: English-everywhere table, i18n (`i18n.CATALOG` + `t()`, en source/ru translation), Conventional Commits, the TODO flow, the smoke commands, and the hard invariants (no `ANTHROPIC_API_KEY`, `setting_sources=[]`, don't widen `SAFE_TOOLS`). | |
| 87 | docs | no `.github/` community templates | Added `PULL_REQUEST_TEMPLATE.md` (what/why · CC type · checklist incl. smoke + i18n EN+RU + TODO link) and `ISSUE_TEMPLATE/{bug_report,feature_request,config}.yml` (`blank_issues_enabled: false`; bug form fields tailored to this bot with a redact-secrets reminder). | |
| 88 | build | no committed linter/test config | Added `pyproject.toml`: `[tool.ruff]` (line-length 100, py311, lean green rule set E4/E7/E9/F/W/B) + `[tool.pytest.ini_options]` so local `ruff`/`pytest` match CI. `ruff check .` clean. | |
| 89 | build | CI lacked least-privilege + concurrency | `.github/workflows/ci.yml` now sets `permissions: contents: read`, a `concurrency` group (`cancel-in-progress`), and `workflow_dispatch`. | |
| 90 | features | favorite/pin sessions (⭐) | Star a session to pin it: `threads.favorite` column + `db.set_favorite`, favorites sort first (`browse_threads ORDER BY favorite DESC`), a ☆/⭐ toggle in `/sessions` (own-session guarded) that marks the name and floats it to the top so important sessions don't need searching. db test added. | |
| 69 | security | DM callbacks acted on an unvalidated session key | `ses:sw`/`qx:`/`stop:` now require `key < 0` and `get_thread(key).chat_id == from_user.id` before acting (same guard as `ses:del`/`ses:fav`). | |
| 70 | ux | long single-line code block emitted empty `<pre></pre>` messages | Added `markup.is_empty_render`; the streamer skips empty code-box chunks in `_commit` + `_render_message_chunks` (keeps the `…` floor for a genuinely empty turn). Test added. | |
| 73 | docs | systemd unit drift | `deploy/tg-bot.service` rebranded "Claude Telegram Bot"; install/enable/journalctl use `claude-tg-bot`; example paths → `/opt/claude-tg-bot`; hardening intact. README already consistent. | |
| 75 | reliability | db.py ran without WAL | `init_db` now sets `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` (best-effort). | |
| 76 | tests | no test for the db migration path | Added `test_forward_migration_adds_columns_with_defaults`: builds the original minimal `threads` schema, calls `init_db`, asserts the new columns default correctly. | |
| 77 | reliability | dead code | Removed `handlers._send_thread_id`, `handlers._grid`, and `db.set_name` (verified zero callers). | |
| 78 | observability | `get_me()` failure showed only a traceback | `bot.main()` logs "Failed to authenticate with Telegram — check TELEGRAM_BOT_TOKEN" before re-raising. | |
| 79 | core | `markup._restore` could corrupt a chunk on a stray stash token | Restore is now a bounded loop with an index check (`0 <= idx < len(placeholders)`), returning the literal token otherwise — also makes nested header/table/link placeholders safe. | |
| 80 | ux | RU `attach.too_large` wording | ru → "Отправьте файл поменьше." | |
| 81 | reliability | `allowlist.add("-")` stored a junk entry | `add()` validates (id all-digits; username `^[A-Za-z0-9_]{4,32}$`) and returns `("invalid", raw)`; `cmd_allow` shows `allow.invalid` instead of a false "granted". | |
| 82 | docs | `handlers.py` docstring was forum-Topics-centric | Added a DM-first / Topics-frozen note to the module docstring. | |
| 83 | ux | `/language` doesn't refresh the `/` command menu | Documented the Telegram limitation (setMyCommands keyed by client `language_code`; no per-user command scope) at both change sites. | |
| 84 | docs | README clone URL hardcodes the GitHub handle | **Won't Do** — it is this repo's real canonical URL (not a secret); left as-is intentionally. | |
| 91 | ux | streaming + DM drafts were two overlapping settings | Merged into the single per-session Streaming toggle; removed the global `draft_streaming` flag, `set_draft_streaming`, and the `/settings` "DM drafts" row. In DM, streaming = drafts; the write-head is documented as dormant. | |
| 92 | ux | markdown headers/links/tables didn't render; transcript Cyrillic was mojibake | `md_to_html` now renders ATX headers → bold, `[t](url)` → `<a>`, and GitHub tables → an aligned `<pre>` grid; `as_document` prepends a UTF-8 BOM for `.md`/`.txt`. Tests added. | |
| 68 | reliability | `reset()` racing an in-flight `handle_text` could orphan a worker | `handle_text` now resolves the record and takes its lock inside a retry loop that re-checks `self._records.get(thread_id) is rec`; if `reset()` popped the record while we blocked on the lock, it retries with the fresh record (the prompt runs on a live record, never lost) instead of building a session + worker on the orphaned one — closing the two-workers-per-thread race. Verified: py_compile + import + 45 tests + live restart. | Fixed a rare race where `/reset` during an in-flight message could spawn a duplicate, untracked worker. |
| 93 | ux | smooth streaming in code mode + live code-block split | Live code-block splitting: `markup.split_closed_blocks` detects a fully-closed fenced block (closing fence + newline) mid-stream; `sessions._split_live_blocks` (after each `update()` in code mode) commits the prose+block prefix as its own copyable message(s) via the new `streamer.flush_segment()` and keeps streaming the tail — a finished snippet is copyable immediately and the DM draft stays smooth (no completed block whose moving close-tag snaps the animation). `segment_break` refactored onto a shared `_begin_next_segment`. An adversarial multi-agent audit then caught + fixed a double-post (a cumulative `text_full` snapshot resurrecting an already-flushed block → `text_full` is now ignored once segmented, matching the result-branch guard) and an O(n²) re-scan on a long unclosed block (cheap fence-count gate). Tests: 7 `split_closed_blocks` units + 2 `_run_one` integration (double-post regression); 47 green; live (Run polling). | Code mode now streams smoothly and breaks each finished code block into its own copyable message live, as it is generated. |
| 94 | ux | spinner in the ⏹ Stop / "working" control | `streamer._delayed_control` animates a braille spinner (`_SPIN_FRAMES`, ~1.2 s cadence, just above Telegram's ~1 edit/sec cap) next to the "working…" label, keeping the ⏹ Stop button on every edit; the loop re-checks the streaming flags under the lock and is torn down by `_remove_control()`/`cancel()` (no orphaned task). Audit follow-up: the control message id is registered + re-checked under the lock right after the send, so a turn ending mid-send can't orphan it. Live. | The ⏹ Stop / "working…" control now shows a live spinner while a turn runs. |
| 95 | ux | `/sessions` redesign — tap a session → options menu; New chat/New code buttons; quick actions on switch | Each list row is now a single full-width NAME button → tapping it opens a per-session options menu (✅ Switch · 📋 Recap · ✏️ Rename · ℹ️ Status · ⭐/☆ favorite · 🗑 Delete · ◂ Back). The browser footer gained **💬 New chat** / **🟩 New code** (next to Search/Close). The switch card now carries quick actions (📋 Recap · 📄 Export). Recap/Rename/Status/Export are now key-addressable (`_recap_messages`, `_history_doc`, `_session_options`, key-aware `_do_rename` + a `rename:<key>` pending action); every per-session action is ownership-gated via `_owned_session` (chat_id OR created_by). i18n en/ru parity + 47 tests + ruff green. | The `/sessions` list is scannable — tap a session for a full actions menu; create chat/code sessions right from the browser. |
| 96 | ux | session glyph — code → shell-prompt ▸ | `mode_glyph("code")` → `▸` (shell-prompt / bash-cursor-like) instead of ⌨️; the 6 hardcoded ⌨️ in `i18n.py` (btn.code, cmd.newcode, help + /new chooser) and 2 handler docstrings swapped to ▸; chat stays 💬. i18n en/ru parity tests green. The `/rename`-button ✏️ + per-row list/info icons fold into the #95 `/sessions` redesign (no standalone rename button exists yet). **(Superseded by #107 — code glyph is now 🟩.)** | Code sessions are now marked with a ▸ shell-prompt glyph instead of a keyboard. |
| 97 | core | Unique git-commit-style session ids (short hash, not a position or plain number) | `db.session_sid(thread_id)` = `sha1("sess:"+id).hexdigest()[:6]` — a stable, migration-free PUBLIC id derived from the immutable thread_id, so every existing session gets one immediately. Shown as `<code>{sid}</code>` in `/sessions` rows, the switch card (`session.card_meta`), and `/status` (`status.header`), REPLACING the `enumerate` list position that shifted as sessions were added/removed. Also bumped the row button's name clip 20→40 so long names (e.g. «Пикабу iOS приложение») aren't cut. Typed sid-reference folds into #95/#100. | Sessions now have a fixed short id (e.g. `0d4be1`) instead of a number that shifted. |
| 98 | ux | Merge `/permissions` + `/auto` into one permissions control (Anthropic-style) | One control, four policies — `ask · auto-edits · plan · full-access` — the SDK `bypassPermissions` mode renamed from `yolo` everywhere (`PERM_NAME_TO_MODE`, the `/settings` perm sub-page, `cmd_permissions`, i18n `perm.*`, `permissions.py` comments). `full-access` stays owner-only. `/auto on\|off` is reframed as a thin shortcut for `/permissions full-access\|ask` (its help now says so). One `/settings` row (the perm sub-page). i18n en/ru parity green. | `/permissions` is the single approval control (ask/auto-edits/plan/full-access); `/auto` is just a shortcut. |
| 99 | ux | `/model` + `/effort` offer an interactive picker | No-arg `/model` and `/effort` now pop an inline button picker (current marked ✓) instead of printing the value — `/model` → opus/sonnet/haiku; `/effort` → low/medium/high/xhigh/max/default. Taps hit new `pm:`/`pe:` callbacks (`on_model_pick`/`on_effort_pick`) that set the value, rebuild the session, and edit the message to confirm. | `/model` and `/effort` with no argument show a tap-to-pick menu. |
| 100 | features | Replace `/cwd` + `/dirs` with `/files` (read-only working-dir tree) | Dropped `/cwd` + `/dirs` (a session's working dir is fixed at `BASE_WORKDIR/<key>`) and added `/files` — a read-only, depth/entry-capped tree (`_build_tree`) of the session's working dir, sent inline or as a `files.txt` document when large. Removed both from the command menu + help text; the `set_cwd`/`set_add_dirs` db plumbing is left intact (unused). | `/files` shows the working-dir tree; `/cwd`+`/dirs` retired (working dir is fixed per session). |
| 101 | ux | Arg-capture for ALL arg-commands + document the rule in CLAUDE.md | Free-text arg-commands now PROMPT + capture the next message when invoked with no arg (with a `/cancel` escape) instead of erroring: `/allow` + `/deny` join `/new`, `/rename` (incl. the #95 per-session `rename:<key>`), and `/sessions` Search. Built on the existing module `pending` dict + `_run_pending`; `_do_allow`/`_do_deny` extracted so the direct-arg and captured paths share logic (both owner-gated). Fixed-CHOICE commands (`/model`, `/effort`, `/permissions`, `/usage`, `/memory`, `/language`) keep pickers / `/settings` sub-pages — the better UX than typing. The convention (+ the picker exception) is documented in CLAUDE.md. | Commands that need a value now ask for it (with /cancel) instead of erroring. |
| 102 | security | Per-user access level — chat-only vs chat+code | Allowlist rewritten to a per-entry record map (`allowlist.py`, v2 JSON, fail-closed, 13 unit tests) with a per-user `level` (`chat`/`code`); legacy `{ids,usernames}` migrate to `code`; owner always `code`. Enforced by gating code-session CREATION (`_do_new`, `/newcode`, the `/new` + `/sessions` choosers) and switching INTO / running a turn in a code session (`_access_block` in `on_text`/`_submit`) for non-code users. `/level @user chat|code` changes it; `/users` shows it. The default `/` command menu omits code-mode commands (`/newcode`,`/files`,`/permissions`,`/maxturns`) so chat-only users don't see them (owner chat scope shows all). | Per-user chat-vs-code access — chat-only users can't create/use code sessions or see code commands. |
| 103 | security | Time-limited access — per-user expiry date | Entries carry an optional `expires_at` (UTC date); past it the user is denied inside `Allowlist.is_allowed`, so `AllowlistMiddleware` drops them (fail-closed — an unparseable expiry counts as expired; owner exempt). Granted via `/allow @user [level] until YYYY-MM-DD` or `/expire @user YYYY-MM-DD|never`; `/users` shows it. | Access can expire on a date; expired users are dropped, owner never expires. |
| 104 | isolation | Per-code-session Linux user sandbox (own uid, confined to workdir, perms 6/7) | Opt-in per-code-session **bubblewrap** jail (`config.SANDBOX_CODE`, default OFF). When on, code mode launches `claude` via `deploy/sandbox-claude.sh` (wired through `ClaudeAgentOptions.cli_path` in `engine._enable_sandbox`): dropped to an unprivileged uid (default 65534), filesystem confined to the session workdir (the only rw bind) + a private tmpfs HOME, the subscription credential injected READ-ONLY via `--ro-bind-data` (real `~/.claude` invisible), env wiped with `--clearenv` (no `TELEGRAM_BOT_TOKEN` leak), network kept (resolv.conf target bound so DNS resolves). Verified end-to-end: claude auths + the agent's Bash writes its workdir, while the bot `.env` / secrets / other sessions / `/root` are unreadable; bwrap's userns maps the jail uid to outer-root for host writes so the root-owned workdir is writable (no chown). **Residual P0 (owner-deferred):** the agent shares claude's process so it CAN read the injected token — blocked from escaping the workdir; egress-blocking is a future phase. Also future: cross-restart session-state persistence (HOME is tmpfs) + the perm 6/7 noexec toggle (reserved). | Optional bubblewrap sandbox for code sessions — unprivileged, workdir-confined, secrets unreadable. Enable with `SANDBOX_CODE=1`. |
| 105 | security | Optional per-user token quota + top-up command | Each entry has an optional cumulative `token_grant` (None = unlimited); "used" = `SUM(input+output)` over the user's sessions (`db.get_user_usage_tokens`). Enforced pre-turn in `_access_block`: at/over grant the turn is refused with a remaining message. `/limit @user <tokens>` tops up the grant (`/limit @user off` = unlimited); `/users` shows used/grant. Owner uncapped. | Optional per-user token budget with `/limit` top-ups; over-budget users pause until topped up. |
| 106 | ux | Waiting/Stop control animated braille dots | Removed the spinner animation from `streamer._delayed_control`: it now posts a STATIC "⏳ Working…" + ⏹ Stop message; the rotating-glyph loop and `_SPIN_FRAMES`/`_SPIN_INTERVAL` are deleted (owner: at Telegram's ~1 edit/sec cap the dots read as flicker, not motion). Teardown (`_remove_control`/`cancel`) unchanged. | The "working…" control no longer animates dots — just a static label + Stop. |
| 107 | ux | Code session glyph → 🟩 (terminal-like) | `mode_glyph("code")` → 🟩 (was ▸, #96); the literal `▸` mode-glyphs in `i18n.py` (btn.code, cmd.newcode, help en+ru) + 2 handler docstrings swapped to 🟩; the generic `▸` chevrons (btn.next, lang.row, settings.row_*, deep-link button) left intact; chat stays 💬. i18n en/ru parity tests green. | Code sessions are marked with a big green square (terminal-like). |
| 108 | ux | /recap rendered raw Markdown | `cmd_recap` now renders Claude's stored reply via `markup.md_to_html` (was `escape_html`, which leaked literal `##`/`**`/code fences — the reported bug); the user's echoed prompt stays escaped; a long/code-heavy reply is sent as size-safe rendered chunks (never splitting rendered HTML across a tag). `/history` stays a raw `.md` export. | /recap now shows Claude's reply formatted, not as raw Markdown. |
| 109 | reliability | Dead DM session un-switchable + un-deletable | `db.delete_dm_session` no longer refuses `key >= 0` (the `chat_id` scope already protects shared supergroup rows; guards `user_id > 0`); `delok` honours the bool + new `session.delete_failed` toast (was a false "deleted"); `_session_key` heals a missing/dangling current pointer (re-points to a real negative-key session or mints a default) so a stale pointer can't resurrect an empty row. The stuck «Пикабу iOS приложение» row (a code session that landed at key 0) was migrated 0→-3 (created_by=owner, cwd=workdirs/-3, 7 usage rows preserved, `dm_seq` bumped to 3) so it survives as a normal, switchable, deletable session. | Stuck sessions can now be deleted; the broken «Пикабу» one was recovered. |
| 110 | ux | Retire the streaming on/off setting | `/stream` handler, the `/settings` streaming row, the `_settings_apply` `tog/stream` branch, and the `/status` streaming line are all COMMENTED OUT (not deleted) — DM uses native Telegram streaming (always on), so the toggle was redundant. The plumbing (`sessions.set_stream`, the `stream_enabled` column, `rec.stream_enabled`) is kept intact so streaming/speed control can be restored by uncommenting. | Removed the redundant streaming toggle (native streaming is always on). |
| 111 | ux | Terminal-style code session cards | The code-mode tagline and the `/status` directory line render as a shell prompt — `🟩 …` + `<code>{cwd} $</code>` (`mode.tagline_where` is now a monospace prompt line, `status.directory` → `📂 <code>{cwd} $</code>`); the switch card passes the session's `cwd` into the tagline. Chat sessions keep 💬. | Code sessions look terminal-like (a green-square prompt with the working dir). |
| 112 | features | Export code-session working-directory files (.zip) | New `/export` (code sessions only) + an 📦 Export-files button in the `/sessions` options menu: zips the session's workdir (`_workdir_zip`, in-memory `ZIP_DEFLATED`, capped ~49 MB) and sends it as a Telegram document. Distinct from `/history` (transcript export). | Owner request — pull a code session's files out as a zip. |
| 113 | ux | Post-#95/#98/#100 UX feedback fixes | (1) `/language` (+ the `/settings` picker) now refresh the `/` command menu in the chosen language via a per-chat `BotCommandScopeChat` (`_apply_user_menu`), overriding Telegram's client-language default — and scoping the menu to the user's level (chat-level users never see code commands, closing the #102 menu gap for non-owners). (2) The `/sessions` options menu is re-posted at the bottom after Recap/Status/Export so it stays reachable without scrolling (`_repost_options`). (3) `/files` + `/export` are gated to code sessions (`common.code_only`). (4) Removed the lingering streaming row from `/settings` (header line, `_settings_text`, `_gather_vals`) and dropped `/stream` from the command menu. | RU command menu now follows /language; tidier sessions menu; code-only file commands; no stale streaming setting. |
| 118 | isolation | Owner-only per-session sandbox opt-out (run a code session raw) | New owner-only `/sandbox on\|off` (code sessions): `off` sets a per-session `no_sandbox` flag (new `threads` column + `db.set_no_sandbox`, migrated in) so THIS code session's claude runs WITHOUT the bubblewrap jail even when `SANDBOX_CODE` is on — to tell a sandbox issue apart from a bot bug; `on` re-isolates. The engine sandboxes a code session only when `settings.sandbox_code and not state.no_sandbox`; the flag is owner-set only (command is owner-gated), so guests can never escape. Rebuilds the session on change; in the owner's command menu. | The owner can run a code session with isolation OFF to A/B-test the sandbox vs a bot bug. |
| 115 | isolation | Sandbox #104 — persist code-session state across restarts | The bubblewrap jail's HOME is a private tmpfs, but `~/.claude/projects` is now bind-mounted from a per-session host dir (`BASE_WORKDIR/<key>.sbxstate`, passed as `SBX_STATE`, created in `engine._ensure_client`, removed on session delete) so claude's `resume` survives a client rebuild / bot restart. Verified end-to-end: a brand-new sandboxed client resumed a prior session and recalled the planted word. The credential overlay stays ephemeral. | Sandboxed code sessions keep their context across restarts. |
| 116 | security | Sandbox #104 — resource limit (process cap) | The launcher sets `ulimit -u 512` before exec'ing the jail, blunting a fork-bomb DoS from sandboxed code. (seccomp + cgroup memory/CPU limits — needing a compiled BPF policy / a systemd scope — are noted as lower-priority future hardening, not shipped here.) | Sandboxed code can't fork-bomb the host. |
| 114 | security | Sandbox #104 — network egress allowlist | **Superseded by #119.** Necessary but not sufficient on its own: while the subscription token lives inside the jail it leaks via the bot's own output channel (agent reads it, the bot streams it to the user) and via any allowed data-store (e.g. GitHub) — so a firewall alone can't protect it. Egress was folded into the e2e design (#119), whose credential-broker removes the token from the jail entirely; the A–E egress-mechanism analysis lives on in #119's Details (component 2). | — |
| 117 | isolation | Sandbox #104 — perm 6/7 noexec toggle on the workdir | **Won't do — folded into #119 rationale.** noexec is capability-reduction (counter to the goal of containing, not de-powering, sessions) and weak regardless (interpreters run scripts even from a noexec dir; bwrap 0.8 has no per-bind noexec). Recorded in #119 (component 4) so it isn't re-proposed. | — |
| 120 | security | Per-user subscription rate limits (rolling day/week windows) | `allowlist` entry `rate={day,week}` (None=no cap) + `set_rate`/`rate_of`; `db.get_user_usage_tokens(since=)` + `get_user_usage_breakdown`; enforced pre-turn in `_access_block` over the trailing 24h/7d (no reset job). Set via the per-user card or `/limit @user <n> [day\|week]\|off`. Replaces the #105 lifetime cap; owner exempt. | Per-user daily/weekly token caps. |
| 121 | features | Per-user management card (owner: tap a user → level/expiry/limits/memory/effort/stats) | `/users` lists tappable users → `_render_user_card`/`on_user_cb`: toggle level/global-memory/max-effort, set expiry + day/week caps (arg-capture), clear limits, remove, and per-user usage stats. Owner-only; the owner's own card exposes the global-memory toggle. | Manage each user from one tap-through card. |
| 122 | isolation | Per-user global memory (owner-granted opt-out of `setting_sources=[]`) | `allowlist` `global_memory` (+ owner via `owner_prefs`); `sessions._resolve_global_memory` resolves it for the session owner (`created_by`) and `engine` flips `setting_sources` to `["user"]` (loads `~/.claude` + CLAUDE.md/memory). OFF by default; applies on the next rebuild; the card warns it exposes the owner's `~/.claude`. | Give a user (or yourself) global memory. |
| 123 | security | Per-user effort-`max` gate | `allowlist` `allow_max_effort` (owner always allowed); `/effort` picker hides `max` and both the picker + typed path reject it for un-granted users — stops a guest burning the shared subscription with max thinking. | Only granted users can pick max effort. |
| 124 | features | Web-capable chat (WebSearch/WebFetch) | Chat now ships the read-only web tools auto-allowed (like the Claude apps), reversing #24's tool-free chat; system prompt updated; verified live (the model used WebSearch). | Chat can search the web. |
| 125 | security | Neutralize harness keyword triggers (ultracode/ultrathink) | The bundled CLI acts on `ultracode` (→ multi-agent Workflow) and `ultrathink` (→ effort) keywords. The engine sets `CLAUDE_CODE_DISABLE_WORKFLOWS=1` AND splits the keyword with a space in every prompt (`defuse_triggers`); list = `DEFAULT_KEYWORD_TRIGGERS` + `BLOCKED_PROMPT_KEYWORDS` (env). | ultracode/ultrathink can't burn the subscription. |
| 126 | ux | `/permissions` gated to code sessions | Chat is tool-free (the engine hardcodes `permission_mode="default"`), so `/permissions` + the `/settings` row now say "code only" / are hidden in chat. | Permissions menu only where it applies. |
| 127 | reliability | Stale Stop button after a bot restart | A restart orphans the per-turn control message; tapping its Stop (no live turn) now deletes the dead message instead of lingering forever. | Old Stop buttons clear on tap. |
| 128 | docs | README streaming Bot-API link + Known issues + full-control features | Added the `sendMessageDraft` link to the streaming feature, a Known issues section (Telegram Desktop macOS draft "retype" on long answers; iOS renders fine), and a features bullet for full Telegram management. Also: the "comment-out replaced code, don't delete" convention in AGENTS/CLAUDE/CONTRIBUTING. | — |
| 129 | features | Full per-session Tools page (toggle every tool on/off) | `engine.tools_enabled`/`_resolve_tools` + `CHAT_TOOLS` (replaced the `web_search` bool); `db.threads.tools_enabled` (NULL=default, `[]`=tool-free); `sessions` rebuild-on-change wiring; `/tools` + `/settings → 🧰 Tools` with ✅/⬜ toggles (chat = web tools, code = full toolset, dangerous ones still gated). MCP connectors out of scope (#62/#119). | Configure each session's tools from Telegram. |
| 131 | security | Per-user tool cap (owner restricts which tools a shared user may use) | `allowlist` `tool_cap` (list = allowed tools, None = uncapped) + `tool_cap_of`/`set_tool_cap`; `sessions._resolve_tool_cap` → `engine._resolve_tools` intersects the session's enabled tools with the cap (owner always uncapped). Set from the `/users` card → 🧰 Tools sub-page (toggle each tool; applies to all the user's sessions). Audit-driven follow-up to the #121 batch. | Owner controls which tools each shared user can use. |
| 132 | ux | Settings as the single hub + command-menu declutter + transcript export in /sessions | `/settings` moved to menu position 4 (between `/sessions` and `/rename`); pure-config commands (model/effort/tools/memory/permissions/usage/language) dropped from the `/` menu (still typeable) — navigate from `/settings`; added a `👥 Users` hub row (owner) that opens the per-user list in-place with `➕ Add user` + `◂ Settings`; added `📄 Transcript` export to the `/sessions` options menu; chat settings header no longer shows the inert Permissions line (#121 audit #6). | One settings hub; fewer menu items; transcript export in the sessions menu. |
| 133 | core | Chat-default sessions + upgrade/downgrade to code (mutable type, carry conversation) | Reverses #53: every session is born 💬 chat (one `/new`); `/code` upgrades to a code session (working dir + full tools + approval gate, gated by code-access level), `/chat` downgrades back KEEPING the workdir files. `db.switch_mode` carries the conversation by copying the resumable session id old-mode→new-mode column; BOTH modes now run in the per-session workdir (`engine`), so cross-mode resume finds the transcript (verified live — a chat-planted fact was recalled after upgrade). Session-menu **Convert** button (shown per code-access), `/mode` shows how to switch, the new-chat message hints `/code` only to code-capable users, the chat system prompt tells the model to suggest `/code` for code requests, and `big_memory` now applies to both modes. AGENTS/README + button-label UX convention updated; existing chat sessions reset context once (owner-accepted). | Sessions start as chat and upgrade to code (and back), keeping the conversation. |
| 136 | ux | Sessions/files UX cleanup + sandbox default-on with workdir-only writes | One batch: (1) `/sessions` list drops the `sid` public id — rows lead with icon + **name** only; (2) session options menu packs two-per-row (Transcript · Export files / Delete · Back) instead of one button per row; (3) the switch-card quick action relabeled Export→**Transcript** (same `ses:hist`) and the stale options menu is now deleted when you switch; (4) `/files` shows the session **name**, never the host path (`./workdirs/<id>` leaked the internal numbering + shared parent); export zip named by `sid` not the raw id; (5) **sandbox ON by default** (`SANDBOX_CODE=1`, was opt-in) + `base_workdir` resolved absolute (fixes `SBX_STATE` persistence) + `--remount-ro /` in `deploy/sandbox-claude.sh` so the jail root is read-only: a stray absolute write (e.g. the agent's imagined `/Users/<name>`) now FAILS LOUDLY and the agent retries in the cwd, instead of either polluting the host (un-jailed root) or silently vanishing into throwaway jail space. Verified: writes to workdir/`/tmp`/`HOME`/`~/.claude/projects` still work, `/Users` + `/root` blocked, nothing leaks to host. Removed the `/Users/haritos` host debris the un-jailed agent had created. | List/menu/files no longer leak ids or paths; code sessions are jailed by default and can only write inside their workdir. |
| 137 | reliability | Fix the exit-1 startup failure + the "Not connected" chat-death loop + surface real errors + honest usage + sandbox file perms | Root cause of "Failed to start session: Command failed with exit code 1 … Check stderr output for details" was a **stale `--resume` id** ("No conversation found with session ID"), whose real message the SDK swallowed (it only pipes child stderr when `ClaudeAgentOptions.stderr` is set — the bot never set it). Fixes: (a) **capture stderr** via a `_on_stderr` ring buffer wired into options; (b) **classify + surface** the real reason — `_classify_stderr` maps it to `err.rate_limit` (limit) / generic, logs the tail, and shows it localized instead of the placeholder; (c) **auto-recover stale resume** — `_ensure_client` retries connect ONCE without `--resume` on the resume-not-found signature (never on limit/auth); (d) **"Not connected" loop** (build LOCAL client → connect → publish only on success; `_drop_client()` on every failure path so the next turn reconnects) — this was already in the tree from the audit, verified + retagged #137; (e) **honest usage** — a limit-failed turn now synthesizes a `rejected` five_hour window (`limit_hit` flag) so the footer/pin read "5h ⛔ limited" instead of a stale "5h OK", self-healing on the next success; `usage.window_str` no longer asserts "OK" for an unknown status (new `usage.status.unknown` = "—"); (f) **sandbox file perms** — `umask 077` in the launcher + host-side `chmod 0700` on the workdir/.sbxstate so the agent's outputs are owner-only (verified 600/700, root-owned under 0700 `/root`; cross-session bind isolation already correct). Smoke: py_compile+import+ruff+pytest(60) green, sandbox confinement re-verified, bot re-polling. | The bot no longer dies on a stale resume; errors say what actually went wrong; usage stops lying; sandbox files aren't world-readable. |
| 138 | ux | Unified settings schema (registry + resolver + 3-tier scopes + generic /settings) | New `settings_schema.py`: a frozen `Setting` registry (key·type·choices·default·scopes·view_role·edit_role·name_key + per-scope get/set adapters over EXISTING storage, zero data migration) + `Scope`(SESSION→USER→GLOBAL) / `Role`(GUEST<CHAT<CODE<OWNER) enums + `resolve()`/`resolve_from()` (precedence walk). Added the missing USER-default tier (`db.get/set_user_default` over kv). Owner-approved role matrix (see memory): session+my-default editable by all roles for their own; global owner-only; sandbox/global-memory/default-model/access/caps owner-only & HIDDEN. Generic registry-driven `/settings` hub with 3 scope tabs, role-gated visibility, server-side edit_role re-check on apply (button≠auth — security-reviewed PASS), picker for choices (#101). Sandbox routed through the resolver (inversion hidden in adapter; equality unit-test vs old `sandbox_code and not no_sandbox`) so its scope is finally clear ("Sandbox: on · global default"). Review-fixes: per-tab value shows that scope's contribution via `resolve_from` (not cross-scope resolve); `edit_role>=view_role` asserted at import; dedicated `settings.row_maxturns` label (was duplicating "Model"). Tools-grid + users-admin stay bespoke pages, linked from the hub. +8 tests. | Every setting defined in ONE place with clear scopes/defaults/visibility; sandbox scope no longer confusing. |
| 139 | ux | Single source of truth for command names (commands.py registry) | New `commands.py`: frozen `Cmd(slug, aliases, scope[all/code/owner], in_menu, label{en,ru}, help_group)` + `COMMANDS` tuple — the ONE place command names/descriptions live. `handlers` now DERIVES `_COMMAND_NAMES`/`_CODE_`/`_OWNER_` + `_build_commands()` from it (old literal arrays + the `cmd.*` i18n block commented out, #139). Startup `assert_commands_consistent()` scans live `@router Command(...)` decorators and fails loudly on drift (handler↔registry parity, both locales present). Fixed concrete mismatches: stale `/stop` + `/stream` removed from menu+help (handlers commented out); `/stop` typed-refs in /help + queue.cleared now point to the Stop button; `cmd.new` en/ru reconciled; dead `cmd.cwd/dirs/reset` dropped. Owner-menu order preserved (sandbox last). | Command names can't drift across languages or surfaces again. |
| 140 | ux | Per-session workdirs named by session_sid + one-time migration | Workdirs are now `base_workdir/<session_sid>` (sha1 short hash) not the raw numeric thread_id, for BOTH chat + code (shared architecture; chat already ran in its cwd via #133). `db.allocate_dm_session` + `sessions._default_cwd` derive the sid; `handlers._workdir_zip`/`_ensure_state`/delete-teardown switched to sid. Idempotent `db.migrate_workdirs_to_sid()` (called from `bot.main` after init_db) renames existing `workdirs/<tid>`(+`.sbxstate`)→`<sid>` and updates the stored cwd; commit-correct on rename, realign-only, and crash-after-rename cases (review-fixed: the realign branch wasn't bumping the commit guard → lost write; verified A/B/C on a temp DB). Ran live: `-7`→`fca29e` + 6 cwd realignments, bot re-polling. | Workdir names match the public session id; no internal numbering leaked. |
| 157 | ux | Adopt Telegram's modern rich formatting in markup (strikethrough, spoiler, block quotes incl. expandable) | `markup.md_to_html` now renders `~~strike~~`→`<s>`, double-pipe spoilers→`<tg-spoiler>` (conservative: requires non-space inner edges, so a spaced logical-or stays literal), and `> ` line-runs→`<blockquote>` with long runs (> `EXPANDABLE_BLOCKQUOTE_MIN_LINES`=10) collapsing to `<blockquote expandable>`; inline styles nest inside a quote, code/pre left untouched. Added README "Message formatting" section + Telegram doc links. +6 markup tests (74 total green); ruff clean. Owner picked collapse-long-quotes + spoiler-on via an in-bot preview + question. | Claude's replies now use rich Telegram formatting — strikethrough, spoilers, and collapsible (expandable) block quotes; code blocks keep their one-tap copy. |
| 158 | reliability | Reliable 24/7 supervision: systemd auto-restart + connection watchdog | New `watchdog.py` (dependency-free sd_notify): the bot sends READY=1, then WATCHDOG=1 only after a successful Telegram probe (get_me) every WatchdogSec/2; `bot.py` runs it as a task and cancels it on shutdown. Rewrote `deploy/tg-bot.service` for the real root install with Type=notify + WatchdogSec=180 + Restart=always + StartLimitIntervalSec=0 — force-restarts on a dropped/wedged Telegram connection, never gives up across long outages, restarts on boot. Added optional `deploy/claude-tg-bot-restart.{service,timer}` (daily clean restart vs leaks/stale claude auth). Installed + enabled on the host (replaces the bare manual process that died during the 2026-06-16 Telegram outage and never returned). Robust-startup follow-up: a flaky link exposed a Type=notify start flap (startup get_me timed out BEFORE READY → restart loop) — fixed by sending READY before any network I/O, making the startup get_me non-fatal on network errors, and time-bounding setup_commands; added `deploy/install-systemd.sh` (one-command install that adapts paths/user to the checkout). | The bot self-heals on crashes and dropped Telegram connections, and starts on boot. |
| 159 | ux | /codesplit — owner toggle: each code block as its own message | Telegram mobile lacks a per-code-block copy button (desktop has one); the workaround of sending each fenced block as its OWN message is now a persisted global toggle. `streamer.finish` picks `_render_message_chunks` (split — default) vs `_render_chunks` (inline) from `SessionManager.split_code_messages`; `/codesplit on/off` (owner; inline picker; persisted in kv; next-reply effect) flips it; registered in commands.py + i18n + documented in menu.md (§3.7 + §4.5 matrix). Driven by the owner's on-device copy test (short blockquote copies whole on tap; long/expandable only expands; code copies only the tapped word on mobile). | Owner can switch code blocks between separate messages (easy mobile copy) and inline. |

---

## Deferred

Parked work (revive by moving back to Backlog/Open).

| ID | Pri | Eff | Theme | Title | Reason |
|---|---|---|---|---|---|
| 16 | P3 | L | features | optional voice-note input (transcribe → route as text) | Not supported by the SDK: no subscription-safe STT (no `ANTHROPIC_API_KEY` allowed; chat mode is tool-free). Needs an owner-chosen transcription backend (e.g. a local `faster-whisper`) before it's worth building. |
| 18 | P3 | M | build | public release (tag + GitHub Release notes) | After the repo exists and the first version is stable |
| 62 | P3 | L | features | "Pro" command layer — remainder: `/rewind`, `/resume`, `/mcp`, `/budget`, `/continue` | The safe subset shipped (#23). Remainder deferred per the 2026-06-14 SDK introspection: `/rewind` needs `enable_file_checkpointing` + `replay-user-messages` + `UserMessage.uuid` capture (files-only); `/mcp` conflicts with the tool-free/isolation posture (code-mode only); `/budget` (`max_budget_usd`) is likely a no-op under subscription auth; `/resume`+`/continue` are redundant with the bot's own per-session resume. |