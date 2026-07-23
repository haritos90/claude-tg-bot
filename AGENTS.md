# AGENTS.md

The single source of truth for how this project works, for AI coding agents and human
contributors. Read it before changing code — the invariants in §4 are hard-won and ignoring them
reintroduces real bugs.

This is a private, DM-first Telegram bot: a personal frontend to Claude and Claude Code. Each user
talks to it in a private chat and keeps named, fully-isolated sessions. A session is born a chat and
can be promoted to code and back; the conversation carries across the switch.

- chat — a Claude conversation with the read-only web tools (WebSearch / WebFetch); no terminal,
  files, or code execution.
- code — a full Claude Code agent with a per-session working directory, able to run Bash and edit
  files on the server. Reached by upgrading a chat (`/code`), gated by the user's code-access level;
  `/chat` downgrades back and keeps the workdir files.

Access is owner plus allowlist. Everything runs on the owner's Claude Pro/Max subscription via the
Agent SDK — no Anthropic API key, no per-token billing.

Supergroup/Topics mode is frozen: the forum-Topics-as-sessions code is still present but dormant
until Telegram fixes drafts in groups, so DM is the only live mode. Don't add user-facing Topics
references; keep the dormant group code.

The package layout and module map are in [architecture.md](docs/architecture.md).

---

## 1. Working on the project

Tasks are tracked with [Backlog.md](https://github.com/MrLesk/Backlog.md) in a local `backlog/`
directory (not committed). Code comments reference task numbers as `#N`; those numbers are permanent
and load-bearing, so never renumber or reuse one. Work the task you were handed.

Docs are part of the change, not an afterthought:

- Update the doc a change implies, in the same batch. A schema change updates
  [data-model.md](docs/data-model.md); a menu/command change updates [menu.md](docs/menu.md); a
  config/operational change updates [configuration.md](docs/configuration.md) and `README.md`; a
  production incident updates [troubleshooting.md](docs/troubleshooting.md). Code without its doc
  update is incomplete.
- Never break a doc's structure. Each doc has a documented shape — obey it, and re-read its own
  format preamble before editing rather than guessing.
- Spec voice, English only: declarative, present tense, no first person, no provenance or chat
  quotes. State the decision as a neutral fact.

---

## 2. Build, run, test

```bash
# one-time
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements/base.txt
cp .env.example .env                 # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json

# the Claude Code CLI must be installed and logged in to the subscription:
claude --version                     # must print a version
claude setup-token                   # headless subscription login (no API key)

# smoke test — must exit 0 (no real .env needed, nothing starts polling)
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"

# run
python -m app
```

Development and test extras are in `requirements/dev.txt` (`pytest`, `ruff`); run `pytest -q` and
`ruff check .` before opening a PR. `app.bot` must never start polling or call `load_settings()` at
import time — `main()` runs only via `python -m app` — so the smoke import stays cheap.

---

## 3. Golden rules

1. English is the canonical language. Code, comments, docstrings, docs, identifiers, and commit
   messages are English only (this repo may be released publicly). User-facing strings are localized
   via `i18n.py`: never hardcode one in a handler — add a row to `i18n.CATALOG` and render it with
   `i18n.t(key, lang, …)`. Only the bot's own UI is localized; Claude's output is not. Non-English
   text is allowed only in the three translation surfaces — `i18n.py` `ru` values, `commands.py` `ru`
   labels, `menu.md` bilingual label tables — and nowhere else, including when describing an i18n
   change (reference the `CATALOG` key, give only the English).
2. Secrets and identities stay out of code and git. Secrets live in `.env`, the user list in
   `allowlist.json`; both are gitignored. Never hardcode a token, an `OWNER_ID`, or a user id, and
   never log the token.
3. Subscription, not API. Never set or read `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`; the engine
   strips them from the spawned `claude` environment. Code reaching for an API key is a bug.
4. Isolation is sacred. Every `ClaudeAgentOptions` sets `setting_sources=[]` (see §4). Each session
   gets its own `ClaudeSession`, its own `resume` id, its own `cwd`, and its own message queue; no
   mutable session state is shared across `thread_id`s.
5. Owner plus allowlist access. `access.AllowlistMiddleware` drops every update not from the owner or
   an allowlisted user, and fails closed. Allowlist management is owner-only.
6. Dangerous tools go through the Allow / Deny gate. In code mode, anything outside
   `permissions.SAFE_TOOLS` (Bash, Write, Edit, …) is subject to the inline Allow / Deny gate; what
   actually prompts depends on the session's permission mode (§4). Don't widen `SAFE_TOOLS`
   or move a dangerous tool into `allowed_tools` (see §4) without a deliberate reason.
7. Conventional Commits: `<type>(<scope>): <imperative summary>`.
8. Keep changes small and idiomatic — match the surrounding file, comment the why not the what, and
   don't add abstractions beyond what the task needs.
9. Preserve replaced code as a commented-out block with a task reference. When changing or removing
   existing logic, comment the old version next to the new code (e.g. `# was: <old> — replaced for
   #NNN`) so changes stay auditable and revertible. Exception: a task whose explicit goal is
   removal/cleanup may delete.

---

## 4. Gotchas & hard-won invariants

These are SDK and Telegram traps that have caused real bugs. Re-check them before editing
`engine.py`, `handlers.py`, or `streamer.py`.

### Agent SDK — all SDK code is in `engine.py`

- Isolation is `setting_sources=[]`, not `None`, always. In this SDK `None` loads all filesystem
  settings (user and project, including any `CLAUDE.md`) — the opposite of isolation. `[]` loads
  nothing. A loaded `settings.json` could auto-allow tools the bot keeps out of `allowed_tools`, or
  merge an `ANTHROPIC_API_KEY` into the child. Per-user global memory is injected into the system
  prompt directly (`engine._global_memory_block`), never via `setting_sources`.
- Permission gating hinges on `tools` vs `allowed_tools`. `allowed_tools` is the auto-allow list —
  those tools run without ever calling `can_use_tool`. Dangerous tools must be in `tools` but not
  `allowed_tools`, so they hit the approval gate. Putting one in `allowed_tools` silently bypasses it.
- Chat ships only the web tools, and `tools` is an explicit list, never `None`. `tools=None` makes
  the CLI enable its full default set (Bash, etc.). Pass `["WebSearch","WebFetch"]` for chat (the
  same list in `allowed_tools` so they auto-run — chat has no gate), or `[]` for tool-free. Code mode
  keeps the full toolset with dangerous tools gated.
- The CLI honors prompt keyword triggers even on the SDK path. `ultrathink` escalates per-turn
  effort and `ultracode` opts the turn into multi-agent Workflow orchestration — either burns the one
  shared subscription or bypasses the per-user effort gate. The engine disables Workflows
  (`CLAUDE_CODE_DISABLE_WORKFLOWS=1`) and splits the keyword with a space (`engine.defuse_triggers`).
  Effort is controlled only via `/effort`.
- `RateLimitInfo.utilization` is usually `None` far from a window, so the real percentage comes from
  `usage.fetch_account_usage()` — a read-only GET to `/api/oauth/usage` with the OAuth bearer (not an
  API key, billing preserved). `sessions._usage_poll_loop` refreshes it every 5 minutes and on
  `/status`; all fetches fail soft (keep the prior snapshot).
- Image input has no SDK type — pass the raw Anthropic block. Call `client.query()` in its
  async-iterable form, yielding a `user` message whose `content` is a list of text plus
  `{"type":"image","source":{"type":"base64",…}}` blocks. It works in chat too; keep the per-message
  `session_id` as `"default"` (context comes from `resume`).
- Sessions are durable by default. Both modes resume their persisted session id (saved each turn), so
  context survives a restart or a Stop-button stop. `big_memory` is the 1M-context toggle for both modes,
  requested via the `[1m]` model-id suffix (not the `betas` param, which OAuth ignores); it applies
  to Opus by default. A session's mode is mutable: `/code` and `/chat` carry the conversation by
  copying the resumable session id across mode columns, and both modes run in the per-session workdir
  so the transcript is findable from either. Mode, model, and `big_memory` changes rebuild the client.
- The permission gate enforces the policy itself. The SDK calls `can_use_tool` for every
  non-auto-allowed tool regardless of `permission_mode`, so `permissions.make_callback` must honor
  the mode: `bypassPermissions` auto-allows everything; `acceptEdits` (the default) auto-allows file
  edits and ordinary in-jail Bash — outbound/destructive Bash and the web tools still prompt;
  otherwise dangerous tools prompt. Setting `permission_mode` alone does not stop the prompts.

### Telegram rendering — two paths, never cross them

- Command replies (`handlers.reply`) are authored as HTML directly and sent as-is. Never run them
  through `md_to_html` — it escapes the tags again and the user sees literal `<b>` / `&lt;`.
- Model output (`streamer`) is Markdown → render with `md_to_html`. Split the raw text first
  (`markup.split_markdown`, which repairs fenced blocks across boundaries), then render each chunk.
  Never split already-rendered HTML: a tag cut across a boundary is unbalanced and Telegram rejects it.
- Code blocks render as `<pre>` for the tap-to-copy button.
- Inline button labels are emoji-first and short (1–2 words); keep ≤ 3–4 buttons per row, put
  destructive actions on their own bottom row, and keep `callback_data` ≤ 64 bytes (match the
  `verb:arg` scheme).
- DM streaming is native `sendMessageDraft`. Stream the model text only — never a tool-status block
  or a moving caret, since a changing glyph breaks the growing prefix and Telegram snaps the message
  instead of animating. `draft_id` is a non-zero constant; ~5 updates/sec max. Drafts are ephemeral
  (~30 s), so `finish()` must send a real `sendMessage`; fall back to the write-head only on a
  definitive `TelegramBadRequest`, never on a transient throttle.
- Code mode splits output into messages at each tool boundary (`streamer.segment_break`).
  Intermediate messages are silent; only the final answer pings. Links never preview.
- `/recap` renders model text (`md_to_html`); `/history` is a raw-Markdown `.md` export — do not
  render it.

### Localization — `i18n.py`

- `en` is the source column and is never deleted; `t()` falls back to `en`, then to the raw key.
  Adding a language means adding it to `LANGUAGES` and filling its column; the test suite enforces
  that every locale shares identical `{placeholders}` and HTML tags per row.
- Locale is per-user, resolved once by `LanguageMiddleware` (registered after the allowlist). Resolve
  the acting user's locale, not the owner's.
- Only the bot UI is localized — never model-facing strings, logs, or Claude's output. An in-bot
  `/language` switch sets a per-chat menu (`BotCommandScopeChat`) that also scopes the menu to the
  user's access level.
- i18n values carry their own HTML and go through `reply()` as-is; pre-escape dynamic values before
  passing them as kwargs.

### Async and lifecycle — `sessions.py`

- `stop()` is graceful, `reset()` is forceful. The inline Stop button cancels the gate, drains the
  queue, and calls `session.interrupt()` only (no worker cancel, no disconnect), under `rec.lock`, so
  the worker finishes the turn and `finish()` shows the partial text — context preserved. `/reset`
  cancels the worker, `aclose()`s, and drops the record. Don't reintroduce a worker-cancel into the
  Stop path (the old double-reply / memory-loss bug).
- Never `aclose` a live client while a turn is running. `_get_session` and the mode/model/cwd-change
  path skip the rebuild while the worker is busy and defer it to the next idle message.

### Sessions, identity & access — `db.py` / `handlers.py` / `allowlist.py`

- A DM session is a synthetic negative `thread_id`, minted from kv `dm_seq` with
  `chat_id == user_id == created_by`. Supergroup topics are `>= 0` (0 = General, frozen). The public
  session id (`threads.sid`, a ULID) names the on-disk session directory.
- The per-user current session is a kv pointer (`dm_current:<uid>`) that can dangle; `_session_key`
  must heal it rather than resurrect an empty row.
- DM-row ownership: switch / favorite / delete guards confirm the row belongs to the tapper.
  `db.delete_dm_session` scopes its `DELETE` by `chat_id` and returns a bool — a foreign row is a
  no-op, never reported as success.
- The allowlist is the single access chokepoint — extend `is_allowed`, not the middleware. A per-user
  expiry check belongs inside `is_allowed` (owner branch first so the owner never expires). The
  chat-vs-code level gates code-session creation deeper, not in the middleware. The owner is
  synthesized in memory, never written to `allowlist.json`.

### Settings hub & access model — `settings_schema.py` / `handlers.py`

- One hub: the registry-driven `sx:` hub (session / my defaults / global), with Tools / Usage / Users
  as sub-pages. The old flat `st:` hub is retired. Settings slash commands are thin entry points to
  the same picker — one code path per setting.
- Access is derived, not stored. Each option has an owner-set base access (Hidden / Read-only /
  Delegated). A setting is visible iff `role >= view_role` and access is not Hidden, editable iff
  `role >= edit_role` and access is Delegated; the owner is always Delegated. Value resolution honors
  access, so a stale override for a now-Read-only or Hidden option falls back to global. This is
  re-derived at consumption (`sessions._effective_settings`) so soft-revoke binds at run time, and the
  capability gates apply there (ungranted `max` effort downgrades to `xhigh`, a non-owner
  `full-access` reverts to `default`).
- Code-only rows (permission mode, max turns) are gated by session mode, not user level — hidden on a
  chat session's tab even for a code-level user.

### Sandbox — the jail and its containment stack

Every session's `claude` runs inside a bubblewrap jail; it is part of how the bot runs a session, not
an add-on. All OS and bwrap logic lives in [`deploy/sandbox-claude.sh`](deploy/sandbox-claude.sh)
(shell, not Python), driven by `SBX_*` env set in `engine._enable_sandbox` — the single
Python-to-shell interface, so port that one file per distro. The containment stack around it —
credential broker, egress allowlist, per-session uid, seccomp, cgroup caps — is part of the project
too; each layer has an `.env` off-switch for a host that can't support it, and the bot runs with them
on. The full mechanism and threat model are in [isolation.md](docs/isolation.md). Two traps that keep
biting:

- The jail joins its cgroup via a manual `/sys/fs/cgroup/sbx/<pid>` leaf, not `systemd-run --scope`.
  A scope forks the target under PID 1, so a SIGKILL on the SDK's child orphans the ~500 MB `claude`
  and defeats the idle reaper; the manual leaf keeps the process tree intact.
- The seccomp BPF is a denylist whose fall-through must be ALLOW (DENY is jumped-to only). Invert it
  and every non-denied syscall returns `EPERM` and the process crashes.

### Operating the bot

- The venv is not relocatable — moving the project dir breaks `.venv`; recreate it.
- One poller per token: two poller processes on the same token give a Telegram `409 Conflict`.
  Restart the bot after editing code.

---

## 5. Reference

- [`README.md`](README.md) — setup and the Telegram walkthrough.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — the short contributor version of these rules.
- [architecture.md](docs/architecture.md) — package layout and module map.
- [configuration.md](docs/configuration.md) — every `.env` setting, tunables, and capacity planning.
- [data-model.md](docs/data-model.md) — storage layout and the SQLite schema.
- [isolation.md](docs/isolation.md) — the sandbox and containment stack, with a data-flow diagram.
- [menu.md](docs/menu.md) — commands, menus, and the settings/access model.
- [markup.md](docs/markup.md) and [rich-message-spec.md](docs/rich-message-spec.md) — message
  rendering and the Bot API 10.1 rich-message contract.
- [troubleshooting.md](docs/troubleshooting.md) — operator diagnosis and recovery.

`CLAUDE.md` is a local, gitignored personal overlay; this file is the shared doc every contributor
follows.
