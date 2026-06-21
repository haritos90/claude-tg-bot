# AGENTS.md

**This is the single source of truth for AI coding agents (and human
contributors) working on this project.** Read it before making changes — the
**Gotchas** in §5 are hard-won; ignoring them reintroduces real bugs.

This is a **private Telegram bot** that acts as a personal frontend to Claude and
Claude Code. It is **DM-first**: each user talks to the bot in a private chat,
where the bot keeps named, fully-isolated **sessions** they switch between. A
session is **born a chat and can be promoted to code (and back)** — the type is
**mutable** (#133, reverses the old "fixed at creation" rule #53); the conversation
carries across the switch:

- **chat** — a Claude conversation with the read-only **web** tools (WebSearch /
  WebFetch); no terminal, files, or code execution.
- **code** — a full Claude Code agent with its own per-session working directory,
  capable of running Bash and editing files on the server. Reached by upgrading a
  chat (`/code`), gated by the user's code-access level; `/chat` downgrades back
  (keeping the workdir files). One `/new` creates a chat.

> **Supergroup/Topics mode is FROZEN.** The bot still contains the
> forum-Topics-as-sessions code, but it is dormant "until Telegram fixes drafts in
> groups": the headline UX (smooth streaming via `sendMessageDraft`) works **only
> in private chats**. Don't add user-facing references to Topics; keep the dormant
> group code but treat DM as the only live mode.

Access is an **owner + allowlist** (not a single user). Everything runs on the
owner's **Claude Pro/Max subscription** via the Agent SDK — there is **no
Anthropic API key and no per-token billing**.

---

## 1. Where the work is defined

All tasks live in [`TODO.md`](TODO.md). **Read its "How this file works" section
first** — it is the source of truth for the `Backlog → Open → Closed → Deferred`
lifecycle, the `Pri` / `Eff` / `Theme` columns, and the next-free-ID counter.
Work the task you were handed, or an **Open** one.

- **New idea** → add a row to **Backlog** (+ an optional **Details** block).
- **Closing** a task → move it to **Closed**, fill the **Resolution** column,
  delete its Details block.

**Docs are part of the change, not an afterthought — always update them, never
break their structure.** Every change ships with the doc updates it implies, in
the SAME batch:

- **Always update.** A DB/schema change updates [`data-model.md`](docs/data-model.md);
  a UX/menu/command change updates [`menu.md`](docs/menu.md); a config/env or
  operational change updates `README.md` (and the `CLAUDE.md` "Operating" notes);
  every task moves through the `TODO.md` ledger. A code change with no matching
  doc update is incomplete — treat the docs as the spec, not as commentary.
- **Never break structure.** Each doc has a documented shape — obey it. For
  `TODO.md`: keep the row/Details/Resolution forms, the column sets, table
  ordering, never delete a section's header row, and **keep the next-free-ID
  counter in sync** (it is the max allocated ID + 1 — verify against the actual
  rows, don't trust a stale value). Re-read a doc's own "how this works" / format
  preamble before editing it, rather than guessing the format.
- **Spec voice, English only.** Declarative, present-tense, no first-person, no
  provenance / chat quotes / dated "owner said" lines — see Golden rule 1 and the
  `TODO.md` preamble. State the decision as a neutral fact.

---

## 2. Golden rules

1. **English is the canonical language.** Code, comments, docstrings, docs,
   identifiers, and commit messages are **English only** (this repo may be
   released publicly). User-facing bot strings are **localized** via `i18n.py`:
   English (`en`) is the required source column and other locales (e.g. `ru`)
   are translation layers — see §5. Never hardcode a user-facing string in a
   handler; add a row to the `i18n.CATALOG` table and render it with
   `i18n.t(key, lang, …)`. Only the **bot's own UI** is localized; Claude's
   model output is not (the model already mirrors the user's language).
   **Non-English text (e.g. Cyrillic) is allowed ONLY in the three translation
   surfaces** — `i18n.py` `ru` values, `commands.py` `ru` labels, `menu.md`
   bilingual label tables — and NOWHERE else, including comments, docstrings,
   `TODO.md`, and every other `.md`. This holds even when you are *describing* an
   i18n change: don't paste the localized string into prose or a ledger
   Resolution to show what changed — reference it by its `i18n.CATALOG` key and
   give only the English. Describe a violation; never reproduce it.
2. **Secrets and identities stay out of code and git.** Secrets live in `.env`
   and the user list in `allowlist.json` — **both gitignored**. Never hardcode a
   token, an `OWNER_ID`, or a user id. Never log the token.
3. **Subscription, not API.** Never set or read `ANTHROPIC_API_KEY` /
   `ANTHROPIC_AUTH_TOKEN`. The engine strips them from the spawned `claude` CLI
   environment so the subscription is always used. If you find code reaching for
   an API key, that is a bug.
4. **Isolation is sacred — never let one topic's context reach another.** Every
   `ClaudeAgentOptions` sets **`setting_sources=[]`** (see §5 — `None` would load
   global `~/.claude` / `CLAUDE.md`). Each topic gets its own `ClaudeSession`, its
   own `resume` session id, its own `cwd = BASE_WORKDIR/<thread_id>`, and its own
   message queue. No mutable session state is shared across `thread_id`s. The
   General topic is key `0` and is one more isolated session.
5. **Owner + allowlist access.** `access.AllowlistMiddleware` (outer middleware on
   both `message` and `callback_query`) drops every update that is not from the
   owner or an allowlisted user. It **fails closed** (a missing/corrupt
   `allowlist.json` means owner-only, never everyone). Allowlist *management*
   (`/allow` `/deny` `/users`) is owner-only.
6. **Dangerous tools require an explicit tap.** In code mode, anything outside
   `permissions.SAFE_TOOLS` (Bash, Write, Edit, …) must be approved via the inline
   `Allow` / `Deny` buttons. Don't widen `SAFE_TOOLS` or move a dangerous tool
   into `allowed_tools` (see §5) without a deliberate reason.
7. **Conventional Commits** for messages: `<type>(<scope>): <imperative summary>`
   (e.g. `feat(engine): stream tool status into the topic`).
8. **Keep changes small and idiomatic** — match the surrounding file, comment the
   *why* not the *what*, and don't add abstractions beyond what the task needs.
9. **Preserve replaced code as a commented-out block with a task reference.** When
   changing or removing existing logic, don't delete it outright — comment the old
   version next to the new code, tagged with the task/issue it changed for (e.g.
   `# was: <old> — replaced for #120`), so every change stays auditable and easy to
   revert. **Exception:** a task whose explicit goal IS removal/cleanup may delete
   (e.g. a dead-code sweep like #77). In-tree examples: #110/#118 (toggles commented
   out, not deleted, so they can be restored).

---

## 3. Build, run, test

```bash
# one-time
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json

# the Claude Code CLI must be installed and logged in to the subscription:
claude --version                     # must print a version
claude setup-token                   # headless subscription login (no API key)

# smoke test — must exit 0 (no real .env needed, nothing starts polling)
. .venv/bin/activate
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"

# run
python -m app
```

`app.bot` must never start polling or call `load_settings()` at import time —
`main()` runs only via `python -m app` (`app/__main__.py`) — so the smoke import
stays cheap.

---

## 4. Architecture (module map)

| Path | Responsibility |
|---|---|
| `app/bot.py` | Entry point: wiring, middleware registration, long polling, graceful shutdown. `python -m app` (`app/__main__.py`) calls `main()`. |
| `app/watchdog.py` | systemd liveness watchdog (#158): `ready()` sends `READY=1` before any network I/O; `run()` pings `WATCHDOG=1` only after a successful `get_me` probe, so a wedged/dropped Telegram link force-restarts the unit. No-op off systemd. |
| `app/config.py` | `.env` → `Settings`; warns (does not crash) if `ANTHROPIC_API_KEY` is set. |
| `app/i18n.py` | Localization (l10n) table + `t(key, lang, …)`; `en` canonical, `ru` translation; per-user locale cache; display helpers (`onoff`/`yesno`/`mode_word`). No I/O. |
| `app/core/engine.py` | `ClaudeSession` over `ClaudeSDKClient`; **all** Agent-SDK code lives here, incl. the optional bubblewrap sandbox launcher (`_enable_sandbox`). |
| `app/core/sessions.py` | `SessionManager` — per-thread session + serial worker + chaining queue + `/stop` + usage accumulation. |
| `app/core/token_refresh.py` | Background sweep that refreshes the subscription OAuth credential before it expires (#191). |
| `app/core/schedules.py` | Recurring / one-shot schedule runner (natural-language schedules). |
| `app/core/agent_context.md` | The agent self-description appended to both system prompts; loaded at import by `engine` (runtime asset, co-located). |
| `app/storage/db.py` | `aiosqlite` durable state (`threads` / `usage` / `messages` / `kv` / `rate_history`) — see **Data model** below. Survives restart. |
| `app/storage/archive.py` | Cold storage (#177): `archive_session` gzip-bundles a deleted session's workdir + transcript under `BASE_WORKDIR/_archive/` instead of `rmtree` — fail-safe (live copies kept on a half-write). |
| `app/storage/usage.py` | Formatters for the 5h/7d subscription windows (footer / pinned) + `fetch_account_usage` — the `/api/oauth/usage` GET for the real % (#135). |
| `app/access/access.py` | `AllowlistMiddleware` — drops every non-allowed update. `LanguageMiddleware` — resolves + caches each allowed user's UI locale. |
| `app/access/allowlist.py` | JSON-backed `Allowlist` (ids + usernames); owner always allowed; fail-closed; pins username→id on first contact. |
| `app/access/permissions.py` | `PermissionGate` — `can_use_tool` → inline Allow/Deny via `asyncio.Future`. |
| `app/access/settings_schema.py` | Settings registry + resolver (#138): each setting's type/default, its SESSION→USER→GLOBAL storage tier + adapters, and the derived owner access model (#151). |
| `app/telegram/handlers.py` | aiogram router: commands, text routing, permission callbacks, `setMyCommands`. |
| `app/telegram/commands.py` | Single source of truth for the command set + localized menu labels (#139); handlers derive their menu lists + `setMyCommands` from `COMMANDS` (a startup assert catches drift from the registered handlers). |
| `app/telegram/streamer.py` | Live reply: native `sendMessageDraft` streaming in DM (`segment_break` splits code-mode output into messages), caret-free write-head fallback for groups, silent intermediates, no link previews, usage footer. |
| `app/telegram/markup.py` | Telegram formatting: 4096-safe splitting, Markdown→HTML (`<pre>` code blocks), table→rich-HTML, long-output-as-file. |
| `app/telegram/rich_message.py` | Hand-rolled `sendRichMessage` method (Bot API 10.1, #164) — aiogram ships no binding yet; renders native `<table>` from the HTML `markup` builds. |
| `app/telegram/svg_image.py` | Rasterizes a chat reply's inline `<svg>` diagram to PNG via cairosvg (#295). |
| `app/telegram/table_image.py` | Dormant PNG-table renderer (#162), kept for the wide-table (>20-col) fallback (#243). |

The Agent SDK API is pinned to `claude-agent-sdk==0.2.101`. If you bump it,
re-introspect the message/option types before changing `engine.py`.

Out-of-process helpers live in `deploy/`: `tg-bot.service` (systemd unit) and
`sandbox-claude.sh` (the bubblewrap launcher — see the **Sandbox** gotcha in §5).

### Data model

The full storage layout (the `/var/lib/claude-tg-bot/workdirs` tree, the per-session
`work/` `state/` `secrets.env`, where the OAuth token lives) and the SQLite schema are
specified in **[`data-model.md`](docs/data-model.md)**. Two invariants to keep in mind when
editing `db.py`: durable state is one SQLite DB migrated **forward in place** (only
additive, guarded `ALTER TABLE … ADD COLUMN`), and a DM session's `thread_id` is a
synthetic **negative** id (supergroup topics are `>= 0`, 0 = General). The subscription
token is never in the DB — see `data-model.md` and [`isolation.md`](docs/isolation.md).

---

## 5. Gotchas & hard-won invariants

These are SDK/Telegram traps that have caused real bugs. Re-check them before editing
`engine.py`, `handlers.py`, or `streamer.py`.

### Agent SDK (claude-agent-sdk 0.2.101) — all SDK code is in `engine.py`

- **Isolation is `setting_sources=[]`, NOT `None`, ALWAYS.** In this SDK, `None`
  means "load ALL filesystem settings" (user + project, including any `CLAUDE.md`) —
  the *opposite* of isolation. Pass `[]` (empty list) to load nothing. **#130 fix:**
  `setting_sources` is now **`[]` unconditionally** — GLOBAL MEMORY no longer widens
  it to `["user"]`. The old widening also loaded `~/.claude/settings.json`, whose
  `permissions.allow` could auto-allow tools the bot keeps out of `allowed_tools`
  (bypassing the `can_use_tool` gate) and whose `env` could merge a settings
  `ANTHROPIC_API_KEY` into the child (flip billing). Instead, per-user GLOBAL MEMORY
  (owner-granted via the per-user card / `allowlist.global_memory_of`, resolved for
  the session OWNER by `sessions._resolve_global_memory`, OFF by default) **injects
  the owner's `~/.claude/CLAUDE.md` + `~/.claude/memory/*.md` CONTENT directly** into
  the system prompt — `engine._global_memory_block` (chat: appended to
  `CHAT_SYSTEM_PROMPT`; code: the `claude_code` preset's `append`). So the memory
  reaches the model **without ever loading `settings.json`**, and it works under the
  sandbox too (where the jail HOME has no `~/.claude`, so `["user"]` read nothing).
  Granting it to a NON-owner still exposes the owner's CLAUDE.md content to that user
  — deliberate, owner-gated, and the per-user card warns.
- **Permission gating hinges on `tools` vs `allowed_tools`.** `allowed_tools` is
  the **auto-allow** list — those tools execute *without ever calling*
  `can_use_tool`. So dangerous tools must live in `tools` (the callable universe)
  but **not** in `allowed_tools`; only then do they hit the "ask" path and our
  gate fires. Putting a dangerous tool in `allowed_tools` silently bypasses the
  approval buttons.
- **Chat ships ONLY the web research tools — and `tools` is an EXPLICIT list, never
  `None`.** `tools=None` does NOT mean "no tools": the SDK omits `--tools` and the
  CLI enables its full DEFAULT set (Bash, etc.), so chat would get everything. Pass
  an explicit list — `["WebSearch","WebFetch"]` for chat (web-capable like the
  Claude apps), or `[]` for a truly tool-free chat. The same tools go in
  `allowed_tools` so they AUTO-run (chat has no `can_use_tool` gate). **This
  REVERSES the old "chat is tool-free" rule (#24):** chat is web-capable by
  default; code mode is unchanged (full toolset,
  dangerous tools gated). `allowed_tools=[]` alone never limits the universe — it
  only controls auto-approval.
- **The CLI honours prompt KEYWORD triggers, even on the SDK path — neutralize
  them.** Typing `ultrathink` escalates per-turn effort and `ultracode` opts the
  turn into multi-agent Workflow orchestration — either burns the one shared
  subscription / bypasses the per-user effort gate. The engine disables Workflows in
  the child env (`CLAUDE_CODE_DISABLE_WORKFLOWS=1`) AND splits the keyword with a
  space in the prompt (`engine.defuse_triggers`, list = `DEFAULT_KEYWORD_TRIGGERS` +
  `BLOCKED_PROMPT_KEYWORDS`). Don't remove either guard; effort is controlled only
  via `/effort` (per-user gated — `max` is owner-granted).
- **Subscription auth:** never set `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`;
  the engine strips them from the child env. Their presence forces paid billing.
- **`RateLimitInfo.utilization` is usually `None` — so the real % comes from the
  account endpoint (#135).** The SDK `rate_limit_event` sends a numeric fraction only
  as you approach a window; far from it you get `status="allowed"` with
  `utilization=null`. So `usage.fetch_account_usage()` GETs **`/api/oauth/usage`** (the
  source Claude Code's `/usage` reads) with the subscription OAuth bearer +
  `anthropic-beta: oauth-2025-04-20` — a read-only GET, NOT an API key (billing
  preserved). It reports the REAL per-window % even when idle; normalized to the
  RateLimitInfo shape (the endpoint sends `utilization` as a **percent 0..100** and
  `resets_at` as an **ISO string** — converted to a 0..1 fraction + epoch seconds).
  `sessions._usage_poll_loop` refreshes `rate_by_type` from it every
  `_USAGE_POLL_INTERVAL` (5 min) + on `/status`, so the footer/pinned show live
  numbers; the SDK `rate_limit_event` path still updates it mid-turn. All fetches
  fail soft (keep the prior snapshot). `resets_at` is epoch seconds downstream.
- **Image input has no SDK type — pass the raw Anthropic block.** `ImageContent`
  in the SDK is for MCP *tool results*, not user input. To send a picture, call
  `client.query()` in its **async-iterable** form, yielding a `user` message whose
  `content` is a list of blocks: a `{"type":"text",…}` plus one
  `{"type":"image","source":{"type":"base64","media_type":…,"data":…}}` per image
  (see `engine._send_query`). It works in **chat mode too** — image content is
  model input, not a tool. Context/resume still come from the `resume` option, so
  keep the per-message `session_id` as `"default"`.
- **Sessions are durable by default.** Both modes resume their persisted session
  id (`code_session_id` / `chat_session_id`, saved every turn), so context survives
  a restart / `/stop`. `big_memory` is the 1M-context-window toggle (now for BOTH
  modes, #133) — it no longer gates resume. #134: 1M is requested via the **`[1m]`
  model-id suffix** (`engine._one_m_model`), NOT the `betas` param (ignored under the
  OAuth subscription — "Custom betas are only available for API key users"). Applied
  to **Opus only** by default (auto-included on Max, subscription-billed); Sonnet `[1m]`
  needs paid usage-credits (→ "Usage credits required for 1M context") and Haiku has no
  1M, so on those big_memory has no effect. Widen via env `BIG_MEMORY_1M_MODELS`
  (comma-separated id substrings) only if you've enabled usage-credits. `/reset` clears the
  session ids. A session's **mode is MUTABLE** (#133, reverses #53): `/code` upgrades
  a chat to code, `/chat` downgrades back. `db.switch_mode` carries the conversation
  by copying the resumable session id from the old mode's column into the new mode's;
  BOTH modes run in the per-session workdir (engine) so the transcript is findable
  from either — that's the prerequisite for cross-mode resume. The mode change goes
  through the same rebuild path as a model change (`_get_session` already rebuilds on
  `rec.mode != state.mode`). Changing `big_memory` also triggers a rebuild.
- **The permission gate enforces the policy itself.** The SDK calls `can_use_tool`
  for every non-auto-allowed tool regardless of `permission_mode`, so
  `permissions.make_callback` must honour the mode: `bypassPermissions` (`/auto on`
  / full-access) auto-allows everything; `acceptEdits` auto-allows file edits; otherwise
  dangerous tools prompt. Setting the SDK `permission_mode` alone does NOT stop the
  prompts.

### Telegram rendering — two separate paths, never cross them

- **Command replies (`handlers.reply`)** are authored as HTML directly (`<b>`,
  `<code>`, dynamic values pre-escaped with `markup.escape_html`). Send them
  **as-is**. Do NOT run them through `md_to_html` — that escapes the tags again
  and the user sees literal `<b>` / `&lt;`.
- **Model output (`streamer`)** is Markdown from the model → render with
  `md_to_html`. Always split the **raw** text first (`markup.split_markdown`,
  which repairs fenced blocks across boundaries), THEN render each chunk
  independently. Never split already-rendered HTML: a tag cut across a chunk
  boundary is unbalanced and Telegram rejects (and `_safe()` silently drops) it.
- Code blocks render as `<pre>` so Telegram shows the tap-to-copy button.
- **Inline button labels: emoji-first + short.** Lead with an emoji and keep the
  text to **1–2 words** — users scan icons faster than text (`📊 Stats` beats
  `View Statistics`); a 3-word label like `🟩 Upgrade to code` is the upper bound,
  prefer `🟩 Convert to code`. Keep **≤ 3–4 buttons per row** (mobile width), group
  related actions in one row (e.g. ✅/✖ side by side), put **destructive** actions
  (`🗑 Delete`) on their own row at the bottom, and **paginate** long lists. Every
  button's `callback_data` is capped at **64 bytes** (one emoji = 4 UTF-8 bytes), so
  keep payloads compact — match the existing `verb:arg` callback scheme. (Telegram
  inline-keyboard UX guidance: see the
  [inline keyboard guide](https://botnamefinder.com/blog/telegram-inline-keyboard-builder-guide).)
- **DM streaming is native `sendMessageDraft` (the headline).** In a private chat
  the streamer pushes the growing reply as a message DRAFT (`_render_draft`):
  Telegram animates the appended characters letter-by-letter on the client, far
  smoother than editing (edits cap at ~1/sec → chunky). Hard-won rules:
  - **Stream the model TEXT ONLY** — never a tool-status block or a moving caret.
    A changing trailing/middle glyph breaks the clean growing-PREFIX between
    consecutive drafts, so Telegram snaps the whole message in chunks instead of
    animating. (`_DRAFT_CURSOR=""` for the same reason; the old caret zoo is gone.)
  - **`draft_id` is a non-zero constant** (same id → animated update). **~5
    updates/sec max** (`_DRAFT_INTERVAL=0.2`): sustained <110 ms/update trips a 3 s
    `RetryAfter` (measured live).
  - **Drafts are ephemeral (~30 s)** — `finish()` MUST send a real `sendMessage`
    to persist the answer. Do NOT fall back to the write-head on a transient draft
    error (only on a definitive `TelegramBadRequest`, e.g. a non-private chat) — a
    brief throttle must never silently revert a DM to the chunky write-head.
- **Code mode splits output into messages.** `sessions._run_one` calls
  `streamer.segment_break()` on each tool boundary (code mode), committing the
  current burst as its own message so progress is visible instead of editing a
  scrolled-away one. Intermediate messages are silent (`disable_notification`);
  only the final answer pings. Links never preview (`_NO_PREVIEW`).
- **The write-head (`_render_frame`) is the dormant GROUP fallback** — caret-free
  progressive edits at ~1/sec. Not used in DM.
- **`/recap` renders model text; `/history` does not.** The stored last reply is
  raw model **Markdown**, so `cmd_recap` must run it through `markup.md_to_html`
  (NOT `escape_html`, which leaks literal `**`/fences/`#` headers). The surrounding
  `recap.*` labels are already HTML and the user's echoed prompt stays escaped, so
  only the reply clip is rendered, then the assembled HTML is sent via `reply()`
  as-is (no second `md_to_html` pass). `/history` is a `.md` *document* export —
  raw Markdown is correct there, do not render it.

### Localization (i18n) — `i18n.py`

- **English is the source column; never delete it.** `CATALOG[key]["en"]` must
  exist for every key — `t()` falls back to it when a locale lacks the key, and
  to the raw key when the key itself is unknown (so a missing translation is
  visible, never a crash). Adding a language = add it to `LANGUAGES` and fill its
  column; the test suite (`tests/test_i18n.py`) enforces that `en`/other columns
  share identical `{placeholders}` **and** identical HTML tags per row — a
  mismatch breaks `.format()` or Telegram's HTML parse.
- **Locale is per-USER, resolved once by `LanguageMiddleware`** (outer mw,
  registered AFTER the allowlist so only allowed users are resolved). First
  contact auto-detects from the Telegram client `language_code`
  (`normalize_lang`); an explicit `/language` (or the ⚙️ settings row) persists a
  choice in `db` (`kv` `lang:<uid>`) and updates the cache. Handlers read it with
  the local `_lang(message_or_cb)` helper (→ `i18n.cached_lang(user_id)`); the
  streamer/permission-gate/footer resolve it from the **chat id** (DM
  `chat_id == user_id`). Resolve the **acting user's** locale, not the owner's.
- **Only the bot UI is localized.** Do NOT translate model-facing strings (e.g.
  `PermissionResultDeny(message=…)` goes to the SDK), logs, or Claude's output.
  Command-menu descriptions are localized per `language_code` via
  `setMyCommands` (one call per locale in `setup_commands`) — that default follows
  the Telegram CLIENT language. To make an in-bot `/language` switch actually update
  the `/` menu, `handlers._apply_user_menu` sets a **per-chat** menu
  (`BotCommandScopeChat`) in the chosen language, which overrides the client-language
  default; the same call scopes the menu to the user's access **level** (chat-level
  users don't see code-mode commands — `_CODE_COMMAND_NAMES`).
- **i18n values carry their own HTML** and are sent through `reply()` **as-is**
  (NOT `md_to_html`) — same rule as any command reply (see Telegram rendering).
  Pre-escape dynamic values (`markup.escape_html`) before passing them as kwargs.
- **The chat/code glyph lives in `handlers.py`, not `i18n.py`.** `mode_glyph(mode)`
  + `mode_tagline(...)` (top of `handlers.py`) are the single source of the glyph;
  i18n rows only carry the `{glyph}` placeholder plus a few *literal* copies
  (`btn.code`, `cmd.newcode`, `help.text`). Some glyph characters are **overloaded**
  in `i18n.py` — e.g. `▸` is BOTH a mode glyph and a generic chevron in `btn.next`
  / `lang.row` / `settings.row_*`. Never blanket-replace a glyph char; change only
  the mode-glyph occurrences (and keep en+ru symmetric so the parity test passes).

### Async / lifecycle (`sessions.py`)

- **`stop()` is graceful, `reset()` is forceful.** `/stop` = `gate.cancel_thread`
  + queue drain + `session.interrupt()` only (NO worker cancel, NO disconnect),
  all **under `rec.lock`** — the worker finishes the turn naturally and `finish()`
  shows the partial text, so context is preserved and Telegram never desyncs.
  `/reset` is the forceful path (worker cancel + `aclose()` + drop the record).
  The `_run_one` `CancelledError` path (reset/shutdown only) calls
  `session.interrupt()` + `streamer.cancel()` so the SDK turn and the typing/anim
  tasks aren't orphaned. Don't reintroduce a worker-cancel into `/stop` — that was
  the double-reply / memory-loss bug.
- **Never aclose the live client while a turn is running.** `_get_session` and
  `on_mode_or_model_or_cwd_change` skip the rebuild when the worker is busy
  (returning the live session) and defer it to the next idle message; closing the
  client mid-turn kills the in-flight answer.

### Sessions, identity & access (`db.py` / `handlers.py` / `allowlist.py`)

- **A DM session is a synthetic NEGATIVE `thread_id`.** Minted from kv `dm_seq`
  by `db.allocate_dm_session` with `chat_id == user_id == created_by` and a
  per-key workdir `BASE_WORKDIR/<key>`. Supergroup topics are `>= 0` (0 = General,
  frozen). `thread_id` (the threads PRIMARY KEY) is the only stable id; the short
  public id shown in the UI is `db.session_sid(thread_id)` (`sha1("sess:"+id)[:6]`,
  #97 — shipped).
- **The per-user "current session" is a kv pointer, not a column.** It lives at kv
  `dm_current:<uid>` (`db.get_dm_current` / `set_dm_current`). It can dangle: if
  the pointed-at key is deleted/foreign, `_session_key` must heal it (re-point or
  re-allocate) — an unvalidated pointer otherwise silently resurrects an empty row.
- **DM-row ownership: prefer `created_by`, and check delete's return.** Switch /
  favorite / delete guards must confirm the row belongs to the tapper.
  `db.delete_dm_session(uid, key)` scopes its `DELETE` by `chat_id` and returns a
  **bool** — a row whose stored `chat_id` ≠ the tapper is a silent no-op (rowcount
  0) that must NOT be reported as success. Use `created_by` (equals the creator for
  DM rows) or a browse-membership check for the guard, and honour the bool.
- **Allowlist is the single access chokepoint; extend `is_allowed`, not the
  middleware.** `AllowlistMiddleware.__call__` drops any update where
  `allowlist.is_allowed` is False (fail-closed) — so a per-user **expiry** check
  belongs *inside* `is_allowed` (after the entry match; the owner branch stays
  first so the owner never expires) and fails closed with zero handler changes. A
  per-user **chat-vs-code level** is NOT a middleware concern — it gates code-
  session *creation* deeper (`_do_new` / `cmd_newcode` / `cmd_mode`). The owner is
  never written to `allowlist.json`; it is synthesised in-memory from the
  constructor `owner_id` (level=code, never expires, never capped).
- **Per-user token usage is rolled up from `usage`** (#105 shipped). The `usage`
  table is keyed by `thread_id` only (no user column), so the per-user total is
  `db.get_user_usage_tokens(uid)` = `SUM(input+output) JOIN threads WHERE
  threads.chat_id = :uid` (DM `chat_id == user_id`). The token-quota gate and the
  chat-vs-code **level** gate both run pre-turn in `handlers._access_block` (now
  `_access_block(uid, uname, lang, key)` — takes the identity directly so callback
  handlers like the AI-recap button gate too); both exempt the owner. The per-user
  `level`, `expires_at`, and `token_grant` live in the `allowlist.py` v2 record map.

### Settings hub + access model (`settings_schema.py` / `handlers.py`)

- **One settings hub: the registry-driven `sx:` hub.** `/settings` opens the
  scope-tabbed hub (📍 session / 👤 my defaults / 🌍 global), and Tools / Usage /
  Users are `sx:` sub-pages that return to it. The OLD flat `st:` hub is RETIRED —
  `on_settings_cb` is a thin shim that bounces stale `st:` buttons to the hub; the
  old `_settings_keyboard` / `_settings_text` / `_settings_apply` / `_gather_vals`
  builders are dead-in-place (kept for revert, #141). Don't wire new menus to `st:`.
- **Settings slash commands are thin entry points (#145/#146).** `/model` `/effort`
  `/permissions` `/maxturns` `/language` open the SAME hub picker via
  `_send_setting_picker`; `/memory` `/sandbox` `/auto` toggle in place. There is one
  code path per setting — don't reintroduce a parallel `pm:`/`pe:`/`lang:` picker.
- **Access model is DERIVED, not stored (#151, menu.md §4).** Each option has an
  owner-set BASE access — `Access.HIDDEN` / `READONLY` / `DELEGATED`
  (`settings_schema.BASE_ACCESS_DEFAULTS` per Table 23; owner overrides in
  `db.get/set_access_override`, per-user exceptions in
  `allowlist.access_of`/`set_access_exception`). A setting is VISIBLE iff
  `role >= view_role` AND access != HIDDEN; EDITABLE iff `role >= edit_role` AND
  access == DELEGATED (`ss.can_view_setting` / `can_edit_setting`); the owner is
  always DELEGATED. Value resolution honours access — `ss.resolve_effective` only
  counts a user's session/user value when DELEGATED, else GLOBAL (soft revoke).
  These resolvers are SYNC: `_build_ss_ctx` preloads `access_base` + the user's
  `access_exceptions` into the `Ctx`. **Derived at CONSUMPTION too (#161/151c):**
  `sessions._effective_settings(state)` resolves the effective model / effort /
  permission_mode / max_turns / big_memory for the session OWNER via
  `resolve_effective` and `_build_session`/`_get_session` build the SDK client from
  those — so soft-revoke binds at run time, not just in the hub (a stale override for
  a now-Read-only/Hidden option falls back to global). It also enforces the capability
  gates (151d): ungranted `max` effort downgrades to `xhigh`, non-owner
  `full-access` (bypassPermissions) reverts to `default`. **Still separate:** the
  chat-vs-code `level` gate (allowlist) and per-tool `tool_cap` are NOT yet folded
  into the `Access` matrix (tracked under #161/151d).
- **Code-only rows are gated by SESSION MODE, not user level (menu.md §1.7).**
  `ss.CODE_ONLY` (permission_mode / max_turns / sandbox) + `_ss_code_blocked` hide
  those rows on the session tab of a *chat* session even for a code-level user.

### Sandbox (#104/#180 jail ON by default; #119 hardening OPT-IN)

Code sessions can run `claude` inside a **bubblewrap** jail when `SANDBOX_CODE=1`
(`config.sandbox_code`). `engine._enable_sandbox` points
`ClaudeAgentOptions.cli_path` at `deploy/sandbox-claude.sh` and passes the jail
config via `SBX_*` env — **all OS/bwrap interaction lives in that shell file** (not
Python) so it can be ported per-distro. The jail drops to an unprivileged uid
(`SANDBOX_UID`, default 65534), confines the filesystem to the session workdir (the
only writable bind) + a tmpfs HOME, wipes the env (`--clearenv`), caps processes
(`ulimit -u`, #116), and persists `~/.claude/projects` via a per-session
`<workdir>.sbxstate` bind (`SBX_STATE`, #115) so `resume` survives a rebuild. The
owner can run one session un-jailed with `/sandbox off` (`threads.no_sandbox`,
owner-only) to separate a sandbox issue from a bot bug. bwrap's userns maps the jail
uid to outer-root for host writes, so the workdir is writable **without** a chown —
don't add one.

**Isolation hardening (#119 — OPT-IN, OFF by default).** The bwrap jail above limits
**filesystem** blast radius; #119 closes the rest, each behind its own flag so a botched
rule only affects opted-in turns:

- **Credential broker (`CRED_BROKER=1`, #119b).** The subscription OAuth token stays
  OUTSIDE the jail in a host sidecar (`deploy/cred-broker.py`); the jail gets only a
  far-future DUMMY token + `ANTHROPIC_BASE_URL` at the broker, which injects the REAL
  bearer (read fresh from `~/.claude/.credentials.json`, kept current by #191) and
  forwards to `api.anthropic.com`. Token USABLE but UN-extractable — closes the
  chat-output + allowed-destination exfil channels a firewall alone can't.
- **Egress allowlist (`SANDBOX_EGRESS=1`, #119c — CODE sessions only).** A code jail's
  egress is hard-blocked to LOOPBACK ONLY by a **cgroup-scoped** iptables rule
  (`deploy/egress-setup.sh`: a dedicated `SBX_EGRESS` chain + one `OUTPUT` jump matched by
  `-m cgroup --path sbx` — NEVER a global rule / the policy; the live-VPS lockout trap).
  `claude` reaches Anthropic via the broker; the agent's tools reach allowlisted dev
  hosts (Anthropic + GitHub/PyPI/npm by default; extend via `EGRESS_ALLOW_HOSTS`) via a
  CONNECT proxy (`deploy/egress-proxy.py`); all else dropped, so the proxy is the only
  exit and there's no bypass (design option E). **Chat sessions keep open egress** — no
  Bash/files to exfil, and `WebFetch` needs arbitrary URLs (gated in `engine._enable_sandbox`).
- **Per-session secrets (`/secret`, #119d).** A code user stores their OWN service creds
  in `<sid>/secrets.env` (0600), injected as env vars into THAT jail only; the owner's
  creds never enter any jail.
- **DoS limits + seccomp (#119e).** A per-jail cgroup leaf carries
  `memory.max`/`cpu.max`/`pids.max` (`SANDBOX_MEM_MB`/`SANDBOX_CPU_PERCENT`/`SANDBOX_PIDS_MAX`);
  `SANDBOX_SECCOMP=1` loads an x86_64 denylist BPF (`deploy/make-seccomp.py`) refusing
  ~29 exotic syscalls (ptrace/bpf/kexec/keyctl/module-load/…) via `bwrap --seccomp`.

All mechanism is in `deploy/` shell+standalone (Component 5); Python only sets `SBX_*`
env + runs the sidecars (`bot.main` starts the broker/proxy, sets up + reverts the
firewall, compiles the seccomp blob). **Two hard-won gotchas:** (1) the jail joins the
cgroup via a MANUAL `/sys/fs/cgroup/sbx/<pid>` leaf in `deploy/sandbox-claude.sh`, NOT
`systemd-run --scope` — that forks the target under PID 1, so a SIGKILL on the SDK's
child orphans the ~500 MB `claude` (defeating the #179 reaper); the manual leaf keeps
the tree `SDK→launcher/bwrap→claude` intact. (2) the seccomp BPF must be a DENYLIST
whose **fall-through is ALLOW** and DENY is jumped-to only — invert it and every
non-denied syscall returns EPERM and the process SIGSEGVs; bwrap applies the filter
AFTER its own mounts, so denying `mount`/`pivot_root` is safe. With broker + egress on, a
semi-trusted `code` user is contained (token un-extractable, egress allowlisted, FS
confined); without them, `code` level = trusted users only. **Full architecture +
data-flow diagram: [`isolation.md`](docs/isolation.md).**

### Operating the bot

- The **venv is not relocatable** — renaming/moving the project dir breaks
  `.venv`; recreate it (`rm -rf .venv && python3 -m venv .venv && pip install -r
  requirements.txt`).
- **One poller per token.** Two poller processes on the same token → Telegram
  `409 Conflict`. After editing code, **restart** the bot to apply.

---

## 6. Conventions index

- **Personal overlay:** `CLAUDE.md` is a **local, gitignored** file holding the
  owner's private preferences (subscription-limit-saving habits) and
  deployment-operation notes. Not shared, must not be committed; this file
  (`AGENTS.md`) is the shared doc every contributor follows.
- **Setup & Telegram walkthrough:** [`README.md`](README.md).
- **Data model:** [`data-model.md`](docs/data-model.md) — storage layout (the
  `/var/lib/claude-tg-bot/workdirs` tree), the SQLite schema, and where credentials live.
- **Sandbox & isolation architecture:** [`isolation.md`](docs/isolation.md) — the bwrap jail
  plus the #119 credential broker / egress allowlist / per-session uid / per-session
  secrets / DoS+seccomp scheme, with a data-flow diagram.
