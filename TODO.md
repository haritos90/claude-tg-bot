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

**Next free ID:** 102

---

## Open

Current, actionable work. The bot is **DM-first** and running on the subscription.
As of the **2026-06-14 "finish everything" pass**, the Open backlog is cleared:
the DM overhaul (#44–#46, #50, #52–#61) plus all remaining follow-ups (#11–#13,
#15, #28, #47, #49, #51) and the **#23 pro-command safe subset** (`/effort`,
`/maxturns`, `/dirs`, `/fork`) are shipped and verified (see Closed). Code
snippets now render as their **own messages** so they copy cleanly on every
client; a unit-test suite (#12) runs in CI. Supergroup/Topics mode stays frozen.
Parked: #16 (voice — no SDK STT) and the #23 remainder (see Deferred).

A **2026-06-14 pre-push review** filed findings #64–#89; implementation then
shipped the picked subset (see Closed). A follow-up **live-feedback pass** added
the rendering fixes (headers/links/tables + transcript UTF-8 BOM, #92) and the
streaming/drafts merge (#91), then **cleared most of the review backlog in
parallel** — #69, #70, #73, #75–#83 via five disjoint-file agents (#84 won't-do).
Still **open**: the race-fix **#68**, and the live-feedback redesign **#93–#101**
(A2/A3 smooth code-mode streaming + live code-block split, A4 spinner, `/sessions`
tap-menu + New chat/code, stable session ids, merge `/permissions`+`/auto`,
`/model`+`/effort` pickers, `/files` replacing `/cwd`+`/dirs`, arg-capture
everywhere) — see Backlog. Sequencing: partition A → B → C with a check-in each.

The **secret/hygiene gate passed**: `.env`, `allowlist.json`, `bot.db*`,
`bot.log`, `CLAUDE.md`, `.venv/`, `workdirs/` are correctly gitignored and absent
from `git add --dry-run`; no real `OWNER_ID` / token / bot-id / email appears in
any committable file.

| ID | Pri | Eff | Theme | Title |
|---|---|---|---|---|
| — | — | — | — | _(empty — Open backlog cleared 2026-06-14; promote from Backlog/Deferred when picking up new work)_ |

## Backlog

Not started; promote to Open when picked up.

| ID | Pri | Eff | Theme | Title |
|---|---|---|---|---|
| 68 | P2 | S | reliability | `reset()` racing an in-flight `handle_text` can orphan a record/worker |
| 93 | P1 | L | ux | A2/A3 — smooth streaming in code mode + split code blocks LIVE during generation |
| 94 | P2 | S | ux | A4 — spinner animation in the ⏹ Stop / "working" control message |
| 95 | P1 | L | ux | `/sessions` redesign — tap a session → options menu; New chat/New code buttons; quick actions on switch |
| 96 | P3 | S | ux | Session emojis — code glyph → bash-cursor, `/rename` → ✏️, list + info icons |
| 97 | P2 | M | core | Stable internal session IDs (stop sequential numbering; address sessions by id) |
| 98 | P2 | M | ux | Merge `/permissions` + `/auto` into one permissions control (Anthropic-style) |
| 99 | P2 | S | ux | `/model` + `/effort` offer an interactive picker (like `/settings` sub-pages) |
| 100 | P2 | M | features | Replace `/cwd` + `/dirs` with `/files` (read-only working-dir tree) |
| 101 | P2 | M | ux | Arg-capture for ALL arg-commands + document the rule in CLAUDE.md |

### Details

**#68 — `reset()` racing an in-flight `handle_text` can orphan a worker** (P2 · S
· reliability) — `handle_text` calls `_record(thread_id)` (`sessions.py:247`)
BEFORE acquiring `rec.lock` (`:248`); a `handle_text` that resolved `rec` before
`reset()`'s `pop` but is waiting on the lock will build a session + spawn a worker
on the already-popped record, and the next message creates a SECOND record for the
same `thread_id` → two workers invisible to `stop`/`reset`/`status`. Narrow window,
self-heals next turn. Fix: re-fetch under the lock —
`if self._records.get(thread_id) is not rec: return`.

**#93 — A2/A3: smooth streaming + live code-block split in code mode** (P1 · L ·
ux) — Code mode streams in CHUNKS, not the smooth letter-by-letter draft chat gets:
each burst between tools is committed as its own message (`segment_break`), and code
blocks are only isolated into copyable own-messages AFTER the whole turn finishes.
Goal: stream prose smoothly via the DM draft AND, when a fenced block completes,
commit it as its own message LIVE (detect fence open/close in the running text).
Touches `streamer.py` + `sessions._run_one`; mind the AGENTS §5 draft invariants.

**#94 — A4: spinner in the Stop/working control** (P2 · S · ux) — The separate
"⏹ Stop" control message (#49) is static. Add a small rotating animation (reuse a
caret-glyph set) next to a "working…" label, edited on an interval while the turn
runs and removed when it ends. `streamer.py` control-message path.

**#95 — `/sessions` redesign: tap → options, New chat/code buttons** (P1 · L · ux)
— Too many inline buttons per row. Make each row just the session NAME; tapping it
opens an options menu (Switch · Recap · Rename · Status · ⭐ favorite · 🗑 delete).
Add **New chat** / **New code** to the bottom action row (next to Search/Close). On
switch, offer quick actions (recap / export transcript). `handlers.py` + i18n.

**#96 — session emojis** (P3 · S · ux) — Code-mode glyph → a bash-cursor-like symbol
(e.g. green ▸) instead of ⌨️; `/rename` button → ✏️; fitting icons for the
`/sessions` list and the session-info card. `i18n.py` (`mode_glyph`, button labels).

**#97 — stable internal session IDs** (P2 · M · core) — `/sessions` numbers rows by
list POSITION (`enumerate`), which shifts as sessions are added/removed. Show + use a
STABLE id per session (the existing negative key, shown e.g. as `#<n>`); reference
sessions by that id across switch/rename/delete/files. `db` + `handlers`.

**#98 — merge `/permissions` + `/auto`** (P2 · M · ux) — `/auto on` == `/permissions
yolo`; the two overlap and confuse. Collapse into ONE permissions control (Ask ·
Auto-edits · Plan · Full-access), Claude-Code-style; make `/auto` an alias (or retire
it). One row in `/settings`. `handlers.py` + i18n.

**#99 — `/model` + `/effort` interactive pickers** (P2 · S · ux) — After `/model`
(and `/effort`) with no arg, show an inline picker (like the `/settings` model
sub-page) instead of just printing the current value. `handlers.py`.

**#100 — replace `/cwd` + `/dirs` with `/files`** (P2 · M · features) — Decided: drop
`/cwd` and `/dirs` entirely (a session's working dir is fixed; "extra dirs" confused).
Add `/files` (code sessions): a read-only tree of the working directory so you can SEE
what's there. `handlers.py` + a tree helper.

**#101 — arg-capture everywhere + CLAUDE.md rule** (P2 · M · ux) — Every command that
needs an argument should, with no arg, PROMPT and capture the user's next message as
the value (ideally via bot-suggested commands) — like `/new`/`/rename` already do.
Apply to all arg-commands; document the rule in CLAUDE.md (personal overlay).

---

## Closed

Title-only history.

| ID | Theme | Title | Resolution |
|---|---|---|---|
| 1 | core | aiogram long-polling skeleton, owner allowlist, SQLite per-thread state, topic-as-session routing | Delivered: `bot.py` long polling, `access.AllowlistMiddleware`, `db.py` per-thread SQLite, `handlers.thread_key` routing (0 = General). Running. |
| 2 | engine | chat + code modes via Agent SDK on the subscription; per-thread isolation | Delivered in `engine.py`: `ClaudeSession`, `setting_sources=[]`, API-key-stripped child env, own cwd + `resume`; verified subscription-only (no API key). |
| 3 | ux | Claude-Code-style streaming — write-head + tool-status | `streamer.py` rewritten to a typewriter write-head: `update()` buffers text, a frame loop reveals it progressively and slides a rotating braille caret to the frontier (runs while buffered, spins in place when caught up / before the first token). Live tool-status, chunked/`.md` flush. Evaluated native `sendMessageDraft` — private-chat-only (`TEXTDRAFT_PEER_INVALID` in groups), unusable in the supergroup; write-head kept. See AGENTS §5 + #39. |
| 4 | security | permission gate: inline Allow/Deny for dangerous tools in code mode | Delivered: `permissions.PermissionGate` inline Allow/Deny; `SAFE_TOOLS` auto-allowed; dangerous tools gated via `can_use_tool`. (Owner-only approval split out as #30.) |
| 5 | observability | `/status` surfaces token usage, cache-window timer, subscription rate-limit | Delivered: `cmd_status` shows mode/model/dir, busy/queue, 5-min cache window, subscription windows, and lifetime token totals. |
| 6 | ux | task chaining — queue follow-ups to reuse context + cache | Delivered: per-thread `asyncio.Queue` drained serially in the SAME session (`sessions._worker`), preserving context + prompt cache. |
| 7 | docs | README first-time Telegram setup + "no Premium needed" | Delivered: README covers BotFather, supergroup + Topics, Manage Topics, `OWNER_ID`, and that Telegram Premium is not required. |
| 8 | build | choose and add a LICENSE | Added MIT `LICENSE`, `Copyright (c) 2026 haritos90`. |
| 9 | build | GitHub Actions CI | Added `.github/workflows/ci.yml`: ruff + `py_compile` + import smoke on push/PR to `main` |
| 10 | reliability | systemd unit hardening (Restart=always, resource limits, basic sandboxing) | Hardened `deploy/tg-bot.service`: `ProtectSystem=strict` + `ReadWritePaths` (workdir, db, `~/.claude`), `PrivateTmp`, `MemoryMax`, `NoNewPrivileges`; added the REQUIRED `HOME`/`PATH` env so the `claude` CLI is found + creds reachable under systemd. The host install (`/etc/systemd/system`) is run by the owner. |
| 17 | build | create the private GitHub repo `claude-tg-bot` | Owner created the private repo and pushed it via `gh` (done 2026-06-14). |
| 19 | ux | terminal-faithful rendering with copyable `<pre>` code blocks | Delivered: `markup.md_to_html` emits `<pre>` for one-tap copy and `<pre><code class="language-x">` for fenced blocks with a language (label + highlighting); raw-split-then-render keeps every chunk's tags balanced (`split_markdown`). |
| 20 | security | multi-user allowlist from a gitignored `allowlist.json` | Delivered: `allowlist.py` JSON store (gitignored), fail-closed, owner always allowed, username→id pin on first contact; `/allow` `/deny` `/users` owner-only. |
| 21 | observability | ambient subscription-usage display (`/usage off\|footer\|pinned\|both`) | Delivered: `/usage` modes via `usage.py`; per-window % left; persisted across restart (`db.kv` `rate_snapshot` + pinned msg id). |
| 22 | ux | v1 command palette + `setMyCommands` menu | Delivered: `BOT_COMMANDS` + `setup_commands`; `/permissions` maps `ask\|auto-edits\|plan\|yolo` → SDK `permission_mode`. |
| 24 | engine | chat mode was not tool-free (model used WebSearch in chat) | Set `tools=[]` for chat (not `None`); `None` left the CLI default tools on. See AGENTS.md §5 |
| 25 | ux | command replies showed literal `<b>` / `&lt;` (e.g. `/help`) | `handlers.reply` no longer double-escapes: command HTML is sent as-is, `md_to_html` is only for model output |
| 26 | observability | usage footer showed `5h (n/a)` | `usage.window_str` shows the window status (`OK`/`⚠ high`/`⛔ limited`) when `utilization` is null; `%` shown only when the API sends it |
| 27 | features | implement /context /stream /verbose /rename /close /queue /clearqueue /retry | Shipped from #23: `/context` via `get_context_usage`; `/stream` + `/verbose` in-memory per-thread flags; `/rename` + `/close` via `edit_forum_topic`/`close_forum_topic`; `/queue` + `/clearqueue` manage the chaining queue; `/retry` re-runs the last prompt |
| 29 | reliability | changing /mode·/model·/cwd·/permissions mid-run broke the in-flight turn | `_get_session` never aclose()s/rebuilds while a worker is busy — it returns the live session and defers the rebuild to the next idle message; `on_mode_or_model_or_cwd_change` defers + returns a flag so the handler appends "(applies after the current run finishes)". Functionally tested. |
| 30 | security | tool-approval taps were not owner-restricted | `on_perm_callback` ignores non-owner taps ("Only the owner can approve tools."); only the owner authorizes Bash/Write/Edit in code mode. |
| 31 | security | code-mode blast radius for non-owners | `/cwd` sandboxed under `BASE_WORKDIR` for non-owners (absolute paths + `../` escapes rejected via `relative_to`); `/permissions yolo` is owner-only. Owner unrestricted. |
| 33 | observability | verify the SDK usage-dict keys feeding `db.add_usage` | Verified: `ResultMessage.usage = data["usage"]` is the raw Anthropic API `usage` object (snake_case `input_tokens`/`output_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`) — keys match; added a sync-keeping comment in `db.py`. |
| 34 | ux | `/reset` while busy emitted a redundant "⏹ Execution stopped." | Removed the worker's cancel-path `_notify` — graceful `/stop` interrupts (never cancels), so the worker is only cancelled by `reset()`/shutdown, both of which already report. |
| 35 | ux | graceful `/stop` could surface a spurious error status line | engine sets `_interrupted` in `interrupt()`; `run()` returns quietly on an exception while interrupted, so the streamed partial stands as the final answer (real failures still surface). Functionally tested. |
| 36 | observability | pinned-usage edit + rate DB write fired on every rate event | `_run_one` persists + edits only when `_rate_signature()` changes, skipping repeated identical rate events. |
| 37 | features | file attachments (images, PDF, text/code) | Telegram photos, image files, PDFs, and UTF-8 text/code files are accepted: images/PDFs go to the model as Anthropic content blocks (image / `document`), text files are inlined into the prompt; caption = prompt; works in chat AND code mode. Generic `attachments` plumbing (engine `_send_query` → sessions queue → `run`). Caps: 5 MB image / 20 MB PDF / 1 MB text. Verified live with real image + PDF calls + plumbing tests. Albums arrive as separate turns (one per message). |
| 38 | ux | Claude-Code-style token counts in /status + /context | `_fmt_tokens` abbreviates counts (12345 → "12.3k", 1.2M); `/status` shows `Tokens: Xk in · Yk out` + `Cache: …`, `/context` abbreviates used/total — easier to read than raw digits. |
| 39 | observability | evaluate native Telegram streaming (sendMessageDraft) | Investigated per owner request: real + aiogram-supported (`bot.send_message_draft`, Bot API 9.3+, opened to all bots in 9.5), but tested live → **private-chat-only** (`TEXTDRAFT_PEER_INVALID` for supergroup/topics). Incompatible with the Topics-as-sessions design; kept the write-head (#3). Documented in AGENTS §5. |
| 32 | features | `/memory on\|off` per-topic big memory | New `big_memory` flag + `chat_session_id` column (live `bot.db` migrated). On → chat gets the 1M context beta and resumes its persisted session, so the topic survives restart + `/stop`; off → standard ephemeral chat. Chat session id is ALWAYS persisted (so toggling on keeps the context built so far) but only RESUMED when on; `/reset` clears it. `/status` shows the state. Verified end-to-end. |
| 40 | ux | caret zoo + comfortable speed | 17 caret styles (dots, snake, slashes, glitch glyphs, moon, clock, Pac-Man fwd/back, runner, …) chosen at RANDOM per turn (the signature flourish); text reveal slowed to ~16 chars/sec (was too fast); speed presets calm/normal/fast; style + speed persisted and pickable in `/settings`. |
| 41 | ux | settings menu (`/settings`) + trimmed palette | Inline tap-to-change menu: mode, model, permissions, usage, streaming, verbose, big memory, caret style + speed (✓ marks current, sub-pages, yolo owner-only). `/` palette trimmed to 8 essentials; everything else still works when typed. |
| 42 | ux | arg-capture for free-text commands | `/new` and `/rename` with no argument PROMPT and capture the user's NEXT message as the argument (Telegram sends a picked command immediately); `/cancel` aborts. |
| 43 | engine | math rendered as raw LaTeX in chat | Chat system prompt now tells the model Telegram cannot render LaTeX — write plain Unicode (×, ≈, ², √, …), no `$…$` / `\frac` / `\text`. Robust render-time conversion tracked as #51. |
| 44 | core | DM mode foundation (private chat, isolated) | Private chats route to bot-managed sessions with synthetic NEGATIVE keys that never collide with supergroup topics (≥ 0) or other users; per-user current-session pointer; gate re-keyed by the unique session key; DM-aware `/start`; `/new` creates a DM session; `/sessions` browse/search/switch + info card. Isolation verified. |
| 45 | features | DM smooth generation: native `sendMessageDraft` streaming | DM streams via `send_message_draft` (`streamer._render_draft`): Telegram animates appended chars letter-by-letter. Text-only (no status block / caret) to keep a clean growing prefix; `draft_id` constant; ≤5 updates/sec (`_DRAFT_INTERVAL=0.2`, measured 3s RetryAfter penalty below ~110ms); `finish()` persists a real message; no fallback to write-head on transient errors. Verified live by the owner. |
| 46 | docs | document DM-first overhaul | AGENTS.md reframed to DM-first (intro + §5 streaming/resume/permissions), `streamer.py` row updated; README/CLAUDE refreshed; this TODO updated. |
| 50 | ux | per-session working directory by id | Default cwd is now `BASE_WORKDIR/<session_key>` (set in `allocate_dm_session` + `_ensure_state`); the engine `os.makedirs` it before a code turn (fixed "Working directory does not exist"). |
| 52 | ux | `/rename` for DM sessions | `/rename <name>` (or arg-capture) renames the current DM session via `db.set_session_name`; group path still renames the forum topic. |
| 53 | engine | session mode bound at creation (chat XOR code) | A session's type is FIXED at `/new chat\|code`; `/mode` is read-only (no mutation — it used to corrupt a chat session into code); mode toggle removed from `/settings`. `allocate_dm_session` takes `mode`. |
| 54 | engine | durable context by default | Chat sessions always resume `chat_session_id` across restart/`/stop` (decoupled from `big_memory`, which is now only the 1M-window toggle). Owner confirmed context returns after a restart. |
| 55 | security | code-mode auto-approve actually works | The gate (`permissions.make_callback`) now enforces `permission_mode`: `bypassPermissions` (`/auto on`, owner-only) auto-allows everything, `acceptEdits` auto-allows file edits. Before, `can_use_tool` prompted regardless of the SDK mode. |
| 56 | ux | code-mode output split into messages | `streamer.segment_break()` commits each burst of model text (between tool calls) as its own message so progress is visible; the SDK `result` is not re-shown when segmented. |
| 57 | ux | silent intermediates + no link previews | Streaming/segment messages are silent (`disable_notification`); only the final answer pings; permission prompts still notify. All sends/edits pass `_NO_PREVIEW` (links never expand). |
| 58 | ux | delete DM sessions | 🗑 in `/sessions` → confirm → `sessions.reset` (close subprocess) + `db.delete_dm_session` + remove the workdir + fix the current pointer. Scoped to the user's own negative keys. |
| 59 | ux | retire the caret + tool-status machinery | Caret zoo, `_spinner`, status block, `/settings` caret+speed pages removed (Telegram owns the DM frontier; the caret just flickered). Single streaming standard. **(2026-06-14 audit follow-up:** removed the leftover dead `SessionManager.set_caret_speed` + its `caret_speed` kv-load + the now-unused `CARET_SPEEDS` import in `sessions.py`; the dormant group write-head keeps a fixed `"normal"` pace. The gap the re-audit flagged is closed.) |
| 60 | ux | retire the dead `/verbose` command + plumbing | Removed the `/verbose` handler, `set_verbose`, the `verbose` status-dict key, the `/settings` verbose row, and the `/verbose` menu entry — zero `verbose` references remain in any `.py`. (The previous session completed the code removal but died before closing this + restarting; verified complete + closed 2026-06-14.) |
| 61 | ux | discoverable session creation + full command menu + chat/code style separation | `/newchat` + `/newcode` create immutable-typed sessions in one tap; bare `/new` shows a 💬/⌨️ chooser (`on_new_cb`). `setMyCommands` rebuilt most-used-first with **all** 20 user commands (incl. `/rename`), plus an owner-only chat-scoped menu (`auto`/`allow`/`deny`/`users`) via `BotCommandScopeChat`. Mode glyph (💬/⌨️) + a one-line `mode_tagline` now lead every session surface — creation, switch card, `/status`, `/mode`, `/sessions`. Verified: router builds, all commands register, real DB create path makes distinct chat/code sessions. |
| 11 | ux | code snippets weren't copyable (the real ask behind "telegramify backend") | Root cause (diagnosed by sending the owner a live A/B/C test message): the client copies only the tapped token, never a whole `<pre>` block. Fix: render each fenced code block as its **own message** (`markup.segment_blocks` + `streamer._render_message_chunks`) so long-press → Copy grabs the whole snippet. Also added `~~~` fence support. `telegramify-markdown` NOT adopted — the hand-rolled HTML renderer (copyable `<pre>`, language labels, fence-safe splitting) is better-controlled; closing the dep as won't-do. |
| 12 | tests | unit tests for `markup` split/escape + the `db` layer | Added `tests/` (18 tests, pure `pytest` — async tests wrap `asyncio.run`, no pytest-asyncio needed) covering escape, split round-trip, fence repair, `segment_blocks`, LaTeX conversion + prose/code protection, and the db layer (allocate/get, `/stream` persist, message log, rate history, pro-options, scoped delete). `requirements-dev.txt` + a `pytest -q` CI step + root `conftest.py`. |
| 13 | ux | `/queue` per-item cancel | Queue items carry a per-thread monotonic `qid`; `/queue` lists each pending prompt with a ✖ Cancel button (+ Clear all), `on_queue_cb` → `sessions.cancel_queued(thread_id, qid)` rebuilds the queue minus that id under `rec.lock` (order preserved). Tested. |
| 14 | ux | `/new` deep-link confirm | **Won't Do** — DM-first: a DM session is a synthetic negative key, not a forum topic, so there is no `t.me/c/…` deep-link target. `/sessions` switch + the creation/switch cards already provide navigation; the deep link is only meaningful for the frozen supergroup mode. |
| 15 | observability | per-window rate-limit history trend in `/status` | `rate_history` table (append-only, trimmed to 500) written on each rate-signature change; `/status` shows a small `_sparkline` of utilization per window (5h/7d) when ≥2 numeric points exist (utilization is often null far from a limit, so the trend appears only when meaningful). |
| 16 | features | voice-note input | **Deferred** — not supported by the SDK: there is no subscription-safe STT (no API key allowed; chat mode is tool-free), so transcription would need a heavy local model. Parked pending a chosen STT backend (see Deferred). |
| 23 | features | "Pro" command layer — safe subset | Shipped the SDK-clean subset (per a 2026-06-14 SDK introspection): `/effort` (`effort`), `/maxturns` (`max_turns`), `/dirs` (`add_dirs`, code, sandboxed for non-owners), `/fork` (`resume` + one-shot `fork_session`, branch id persisted then flag cleared). Persisted as `threads` columns; a change rebuilds the session (same busy-guard as `/model`). Remainder (`/rewind`, `/resume`, `/mcp`, `/budget`, `/continue`) deferred — see Deferred #62. |
| 28 | ux | persist the per-session `/stream` flag | Added a `stream_enabled` `threads` column; `set_stream` persists it and `_get_session` restores it into the record on (re)build — survives restart. |
| 47 | features | `/history` (export transcript) + `/recap` (last exchange) | Added a `messages` table; `sessions._run_one` logs the user prompt + assistant reply each turn (cleared by `/reset` and session delete). `/recap` shows the last exchange; `/history` exports the full transcript as a `.md` document. |
| 49 | ux | inline ⏹ Stop button | Worked around the draft/`reply_markup` limitation with a SEPARATE control message: the streamer posts a ⏹ Stop message only once a turn outlasts `_CONTROL_DELAY` (3s, so quick replies don't flicker) and removes it when the turn ends; `on_stop_cb` → `sessions.stop` (graceful). |
| 51 | ux | render-time LaTeX→Unicode | `markup._latex_to_unicode` runs inside `md_to_html` AFTER code is stashed (so code spans/blocks are never touched): converts `\frac`/`\sqrt`/`\times`/greek/arrows, `^{}`/`_{}` scripts, and strips `$…$`/`\(…\)` math delimiters — guarded so prose like "$5 and $10", `_italic_`, and `a_b` are preserved. Tested. |
| 63 | features | localize the bot UI (Russian) + per-user language selection | New `i18n.py` extensible l10n table (rows = keys, cols = languages; `en` canonical, `ru` translation; `t()` falls back en→key, gracefully ignores bad format args; `onoff`/`yesno`/`mode_word` helpers; `lang` is positional-only so a `{lang}`-style placeholder can't collide). Every user-facing string across `handlers.py`/`permissions.py`/`usage.py`/`sessions.py`/`streamer.py`/`engine.py` routes through `t()` with the acting user's locale; engine error events carry a stable `error_key` localized at the consumer. Per-user locale auto-detected from the Telegram `language_code` by a new `access.LanguageMiddleware`, cached in `i18n`, persisted in `db` (`kv` `lang:<uid>`), overridable via `/language` (+ a 🌐 `/settings` row). `setMyCommands` registered per locale (incl. owner scope). Scope is UI only — Claude's output is untouched; comments/docstrings/docs stay English. Adversarial multi-agent audit run; all findings fixed. `tests/test_i18n.py` (13 tests) enforces en/ru placeholder + HTML-tag parity and render-without-crash; ruff + 31 tests green; verified live (RU command menu registered with Telegram). |
| 64 | reliability | graceful shutdown never tore down live sessions | `bot.py` `main()` `finally` now `await sessions.aclose()` BEFORE `close_db()`, so live `claude` subprocesses disconnect, workers cancel, and best-effort writes aren't aimed at a closed DB. Verified (import + tests). |
| 65 | security | global usage-mode / draft-streaming writable by any non-owner | Owner-gated the mutations: `/usage <mode>` rejects non-owners (`common.owner_only_usage`); the settings `usage` + `drafts` rows are hidden for guests and `_settings_apply` ignores their taps. `/stream` stays per-session. |
| 66 | reliability | rendered HTML chunk could exceed 4096 → silently dropped | Added `markup.render_within_limit` (+ `HARD_LIMIT=4096`): renders each raw chunk and re-splits the RAW source when the HTML overflows (never splitting rendered HTML), with a hard-cut floor; `streamer._render_chunks`/`_render_message_chunks` use it, footer gate moved to `HARD_LIMIT`. Test added. |
| 67 | docs | README described the FROZEN supergroup/Topics flow as the architecture | Rewrote the "How it works" diagram + "Part A" setup around DM → `/new` → isolated session; fixed the Commands table (added `/newchat`·`/newcode`·`/sessions`·`/rename`·`/history`·`/recap`·`/settings`; `/mode` marked read-only; `/usage`·`/auto` marked owner); replaced remaining "topic"/"group" wording with "session"/DM. |
| 71 | ux | `/recap` + `/history` empty-state misled when the model still had context | The empty branch now checks for a persisted `code_session_id`/`chat_session_id` and shows `recap.empty_has_context` ("older/resumed context isn't in the transcript; new messages are saved from now on") instead of "no conversation logged." en+ru added. |
| 72 | ux | `/sessions` name + 🗑 were equal-width | Redesigned the DM row: the session name is a full-width button over a compact controls row (favorite + 🗑), so the name reads cleanly and the trash is a small half-width control (Telegram forces equal width + centered text within a row). |
| 74 | build | thin `.gitignore` | Expanded to a full Python block (`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`.coverage`/`htmlcov`/`.tox`/`.eggs`/`*.egg`), cross-platform OS + editor sections, and `.env` + `.env.*` with `!.env.example`; kept `CLAUDE.md`/`.claude/` + secret/runtime entries. |
| 85 | security | no `SECURITY.md` | Added a security policy: private disclosure via GitHub advisory, what to include + redact, Scope, and In/Out-of-scope tailored to this bot (token/allowlist/session leakage, permission-gate bypass, `/cwd`+`/dirs` escape, allowlist-fail-open, `ANTHROPIC_API_KEY` paid-billing, isolation; upstream SDK/host out of scope). |
| 86 | docs | no `CONTRIBUTING.md` | Added a contributor guide distilling the AGENTS golden rules: English-everywhere table, i18n (`i18n.CATALOG` + `t()`, en source/ru translation), Conventional Commits, the TODO flow, the smoke commands, and the hard invariants (no `ANTHROPIC_API_KEY`, `setting_sources=[]`, don't widen `SAFE_TOOLS`). |
| 87 | docs | no `.github/` community templates | Added `PULL_REQUEST_TEMPLATE.md` (what/why · CC type · checklist incl. smoke + i18n EN+RU + TODO link) and `ISSUE_TEMPLATE/{bug_report,feature_request,config}.yml` (`blank_issues_enabled: false`; bug form fields tailored to this bot with a redact-secrets reminder). |
| 88 | build | no committed linter/test config | Added `pyproject.toml`: `[tool.ruff]` (line-length 100, py311, lean green rule set E4/E7/E9/F/W/B) + `[tool.pytest.ini_options]` so local `ruff`/`pytest` match CI. `ruff check .` clean. |
| 89 | build | CI lacked least-privilege + concurrency | `.github/workflows/ci.yml` now sets `permissions: contents: read`, a `concurrency` group (`cancel-in-progress`), and `workflow_dispatch`. |
| 90 | features | favorite/pin sessions (⭐) | Star a session to pin it: `threads.favorite` column + `db.set_favorite`, favorites sort first (`browse_threads ORDER BY favorite DESC`), a ☆/⭐ toggle in `/sessions` (own-session guarded) that marks the name and floats it to the top so important sessions don't need searching. db test added. |
| 69 | security | DM callbacks acted on an unvalidated session key | `ses:sw`/`qx:`/`stop:` now require `key < 0` and `get_thread(key).chat_id == from_user.id` before acting (same guard as `ses:del`/`ses:fav`). |
| 70 | ux | long single-line code block emitted empty `<pre></pre>` messages | Added `markup.is_empty_render`; the streamer skips empty code-box chunks in `_commit` + `_render_message_chunks` (keeps the `…` floor for a genuinely empty turn). Test added. |
| 73 | docs | systemd unit drift | `deploy/tg-bot.service` rebranded "Claude Telegram Bot"; install/enable/journalctl use `claude-tg-bot`; example paths → `/opt/claude-tg-bot`; hardening intact. README already consistent. |
| 75 | reliability | db.py ran without WAL | `init_db` now sets `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` (best-effort). |
| 76 | tests | no test for the db migration path | Added `test_forward_migration_adds_columns_with_defaults`: builds the original minimal `threads` schema, calls `init_db`, asserts the new columns default correctly. |
| 77 | reliability | dead code | Removed `handlers._send_thread_id`, `handlers._grid`, and `db.set_name` (verified zero callers). |
| 78 | observability | `get_me()` failure showed only a traceback | `bot.main()` logs "Failed to authenticate with Telegram — check TELEGRAM_BOT_TOKEN" before re-raising. |
| 79 | core | `markup._restore` could corrupt a chunk on a stray stash token | Restore is now a bounded loop with an index check (`0 <= idx < len(placeholders)`), returning the literal token otherwise — also makes nested header/table/link placeholders safe. |
| 80 | ux | RU `attach.too_large` wording | ru → "Отправьте файл поменьше." |
| 81 | reliability | `allowlist.add("-")` stored a junk entry | `add()` validates (id all-digits; username `^[A-Za-z0-9_]{4,32}$`) and returns `("invalid", raw)`; `cmd_allow` shows `allow.invalid` instead of a false "granted". |
| 82 | docs | `handlers.py` docstring was forum-Topics-centric | Added a DM-first / Topics-frozen note to the module docstring. |
| 83 | ux | `/language` doesn't refresh the `/` command menu | Documented the Telegram limitation (setMyCommands keyed by client `language_code`; no per-user command scope) at both change sites. |
| 84 | docs | README clone URL hardcodes the GitHub handle | **Won't Do** — it is this repo's real canonical URL (not a secret); left as-is intentionally. |
| 91 | ux | streaming + DM drafts were two overlapping settings | Merged into the single per-session Streaming toggle; removed the global `draft_streaming` flag, `set_draft_streaming`, and the `/settings` "DM drafts" row. In DM, streaming = drafts; the write-head is documented as dormant. |
| 92 | ux | markdown headers/links/tables didn't render; transcript Cyrillic was mojibake | `md_to_html` now renders ATX headers → bold, `[t](url)` → `<a>`, and GitHub tables → an aligned `<pre>` grid; `as_document` prepends a UTF-8 BOM for `.md`/`.txt`. Tests added. |

---

## Deferred

Parked work (revive by moving back to Backlog/Open).

| ID | Pri | Eff | Theme | Title | Reason |
|---|---|---|---|---|---|
| 16 | P3 | L | features | optional voice-note input (transcribe → route as text) | Not supported by the SDK: no subscription-safe STT (no `ANTHROPIC_API_KEY` allowed; chat mode is tool-free). Needs an owner-chosen transcription backend (e.g. a local `faster-whisper`) before it's worth building. |
| 18 | P3 | M | build | public release (tag + GitHub Release notes) | After the repo exists and the first version is stable |
| 62 | P3 | L | features | "Pro" command layer — remainder: `/rewind`, `/resume`, `/mcp`, `/budget`, `/continue` | The safe subset shipped (#23). Remainder deferred per the 2026-06-14 SDK introspection: `/rewind` needs `enable_file_checkpointing` + `replay-user-messages` + `UserMessage.uuid` capture (files-only); `/mcp` conflicts with the tool-free/isolation posture (code-mode only); `/budget` (`max_budget_usd`) is likely a no-op under subscription auth; `/resume`+`/continue` are redundant with the bot's own per-session resume. |
