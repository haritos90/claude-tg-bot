# Troubleshooting runbook

Operator-facing diagnosis + recovery for production incidents. Each entry follows the same
shape: **symptom → mental model → fast diagnosis (copy-paste) → recovery → the fix in code**.
Keep it concrete and link the deep specs rather than restating them.

Setup assumed below: the bot runs under systemd as `claude-tg-bot` (logs:
`journalctl -u claude-tg-bot`); every turn runs a jailed `claude` CLI under `bwrap`; the
credential broker is `deploy/cred-broker.py` on `127.0.0.1:8789` and the egress proxy is
`deploy/egress-proxy.py` on `127.0.0.1:8790`. Architecture: [`isolation.md`](isolation.md).

---

## Stuck `<tg-thinking>` ("Thinking…") draft — the live indicator never resolves

**Symptom.** In a DM, the animated "Thinking…" draft (the live streaming indicator) stays on
screen indefinitely and never becomes an answer. The session looks unresponsive — new
messages queue behind the wedged turn.

**Mental model — read this first, it is counter-intuitive.**

- DM streaming uses Telegram **rich-message drafts** (`sendRichMessageDraft`); the
  `<tg-thinking>` block shows until the real answer replaces it. The streamer re-sends the
  draft every ~12 s (`_DRAFT_KEEPALIVE_SECS`) to keep it alive while the turn runs.
- A draft is **cleared only when a real message lands in that chat** — the final
  `sendRichMessage` that every normal turn sends via `streamer.finish()`. The Bot API has
  **no draft delete/clear method**, and empty content shows "Thinking…" (not a clear) — see
  [`rich-message-spec.md`](rich-message-spec.md). The docs' "~30 s ephemeral preview" does
  **NOT** reliably remove an *orphaned* draft from the client UI: the stale frame is **cached
  client-side** and lingers until the client re-syncs — i.e. until a new real message lands in
  the chat **or the Telegram client is restarted** (both confirmed 2026-06-27 to clear it;
  otherwise the frame survived minutes).
- Therefore: **a turn that never reaches `finish()` never clears its draft**, and the
  keepalive animates "Thinking…" forever.

**Two root causes seen.**

1. **Engine wedge after reasoning — fixed.** A `thinking_delta` is a `StreamEvent`,
   so it sets `_progressed=True` and disarms the first-token watchdog
   (`_FIRST_TOKEN_TIMEOUT_SEC`). If the upstream/CLI then goes silent — e.g. the jailed
   `claude` completes its model calls but emits no final result — the engine's per-event
   `await` was **unbounded**, so the turn hung and the keepalive held the draft. Fixed by a
   second watchdog `_STALL_TIMEOUT_SEC` (env `MODEL_STALL_TIMEOUT_SEC`, default 180 s) that
   bounds the wait while the turn is still in the **thinking phase** (progressed, but no
   answer content yet — tracked by the `_answered` flag). Once real answer text / a tool call
   / a result starts, the wait stays unbounded (a long tool call or build legitimately emits
   nothing for minutes).
2. **Turn interrupted by a restart before it finished.** Restarts are **soft**: `systemctl
   restart` → SIGTERM → a graceful ~40 s drain (`sessions.drain`) → `aclose()`. A turn that
   **finishes within the drain** reaches `finish()` and clears its draft normally. But a turn
   **still running when the 40 s drain times out** (a wedged turn, or a genuinely long tool
   call / build) is **cancelled** — the `CancelledError` path runs `streamer.cancel()`, NOT
   `finish()` — so no final message is sent and the draft is **orphaned**. (A real crash —
   SIGKILL / OOM — kills immediately, same result.) It won't clear on its own; only the next
   real message in that chat does.

**Fast diagnosis (copy-paste).**

```bash
# 1) Is a turn wedged? A chat turn takes seconds; a jail alive for minutes is suspect.
pgrep -af bwrap
ps -e -o pid,etime,stat,comm | grep -E 'bwrap|claude'      # ages + state; spot the inner `claude`

# 2) What is the jailed claude blocked on? (root reads its /proc across the userns)
PID=<inner claude pid>; grep State /proc/$PID/status; echo "wchan: $(cat /proc/$PID/wchan)"

# 3) Did the model calls actually complete? "[broker] ... -> 200" is logged only AFTER the
#    SSE response was streamed in full.
journalctl -u claude-tg-bot --since "-15min" | grep '\[broker\]'

# 4) Is the broker still talking upstream, or already idle? A live mid-stream turn has a
#    broker -> api.anthropic.com:443 ESTAB; none + claude waiting on :8789 = broker idle, CLI wedged.
ss -tnp | grep -E ':8789|:443'

# 5) Hung web tool (chat sessions have WebSearch/WebFetch)? Look for an egress-proxy outbound.
ss -tnp | grep 'pid=<egress-proxy pid>' | grep -v ':8790'

# 6) Did a watchdog fire? No "turn stalled" + a wedged turn = the disarmed-watchdog
#    gap, now covered by the stall watchdog.
journalctl -u claude-tg-bot --since "-30min" | grep -iE 'turn stalled|service unavailable'
```

Interpretation: model calls returned `-> 200` **but** the turn never finished and no
`turn stalled` was logged ⇒ the engine was parked in the unbounded post-reasoning `await`
(root cause #1). A jailed `claude` in `do_epoll_wait` with **no** open sockets = it finished
its API work and went idle without emitting a result — a CLI/upstream-side stall the bot
can't fix from inside; the stall watchdog is the bot-side safety net that ends the turn.

**Recovery.**

- **Clear a stuck draft (immediate), user-side:** the orphaned frame is **cached
  client-side**, so it clears as soon as the client re-syncs. Either (a) **restart the
  Telegram client** (close/reopen the app — confirmed 2026-06-27 to clear it), or (b) send any
  message to the chat — e.g. `/status` — so a real message lands and the client updates. The
  **bot cannot force-clear a draft** (no API for it); don't hunt for one.
- **Kill a wedged turn:** `systemctl restart claude-tg-bot` frees the session and kills the
  jailed subprocess. **Caveat:** the restart is graceful (~40 s drain), but a turn that doesn't
  finish in that window is **cancelled** (`streamer.cancel()`, not `finish()`), so no final
  message is sent — the draft is **orphaned** and the user still has to send a message (or
  restart their client) to clear the visual. Sending a clearing message via the bot token is an
  outbound publish under the bot's identity (gated) — don't do it unprompted.

**The fix in code.** `app/core/engine.py` — `_STALL_TIMEOUT_SEC` plus the `_answered`-gated
three-way wait in `ClaudeSession.run()`. On fire it `aclose()`s the stream, drops the client
(killing the wedged subprocess) and yields `err.service_unavailable`, which the streamer
commits via `finish()` — a real message that clears the draft. Tunable via
`MODEL_STALL_TIMEOUT_SEC` (`0` disables). Tests: `tests/test_engine.py` —
`test_stall_after_reasoning_surfaces_service_unavailable` and
`test_reasoning_then_answer_does_not_false_timeout`.

**Known limitation / possible future work.** A restart while a turn is **still in flight past
the ~40 s drain** (a long healthy tool call / build, or — before the fix — a wedged turn) cancels it
via `streamer.cancel()` without reaching `finish()`, orphaning its draft (there is no
shutdown-finalize). A shutdown hook that commits in-flight turns to a real message would close
that gap, but it would post a message on each such restart — weigh against the "keep background
events silent" preference before adding it.

---

## "The model declined … cybersecurity safeguards" (was "Invalid request to the model") — a refusal, not a bug

**Symptom.** A turn cuts off mid-answer (or returns no answer) and the bot posts a refusal
notice — since the relabel, `⚠️ The model declined this turn under its cybersecurity
safeguards …`; older builds showed the misleading `⚠️ Invalid request to the model.` Typically
after a conversation drifts into security / exploit / jailbreak territory.

**Mental model.**

- The model can **refuse** a turn. The API delivers a refusal as a **synthetic assistant
  message**, not an HTTP error: the request **succeeds (HTTP 200)** and the refusal rides in the
  response body — `stop_reason: "refusal"`, `stop_details.category` (e.g. `"cyber"`),
  `error: "invalid_request"`, and a `text` block explaining it ("…flagged this message for a
  cybersecurity topic… apply for an exemption… try rephrasing in a new session or change your
  model").
- The SDK surfaces this as `AssistantMessage.error == "invalid_request"` **with**
  `stop_reason == "refusal"`. Two traps this creates: (a) the broker logs `[broker] POST
  /v1/messages -> 200` — there is **no 400**, so status-code hunting misleads; (b) the engine
  does not log `invalid_request` (only auth/billing warn), so the **bot log is silent** — the
  real reason lives only in the CLI transcript.
- The SDK exposes `error` + `stop_reason` + `content` but **not** `stop_details`, so the *cyber*
  category is read off the explanation text (`_CYBER_REFUSAL_MARKERS`). A reworded safeguard
  simply falls back to the generic refusal message — never back to the "invalid request"
  mislabel.

**Fast diagnosis (copy-paste).**

```bash
# The broker shows 200 — a refusal is in-body, NOT a 400:
journalctl -u claude-tg-bot --since "-15min" | grep '\[broker\] POST /v1/messages '

# The real reason is in the CLI transcript (JSONL). Find the session's workdir + grep it:
#   <BASE_WORKDIR>/<ULID>/state/<encoded-cwd>/<session>.jsonl
W=/var/lib/claude-tg-bot/workdirs
grep -ho '"stop_reason":"refusal".*"category":"[a-z]*"' "$W"/*/state/*/*.jsonl | tail
grep -ho 'flagged this message for a[^"]*'              "$W"/*/state/*/*.jsonl | tail
```

**Recovery (user-side).** Start a **new session** (`/new`) and ask the specific factual question
directly — a fresh context usually clears the accumulated framing that tipped the safeguard;
or **switch model** (`/model`); or apply via the exemption form the CLI links. This is a
model-side policy decision — the bot cannot override it.

**The fix in code.** `app/core/engine.py` — `_refine_error()` detects `stop_reason == "refusal"`
+ `invalid_request`, classifies cyber vs. generic off the explanation text
(`_CYBER_REFUSAL_MARKERS`, since the SDK omits `stop_details`), and yields `err.cyber_refusal` /
`err.model_refusal` (localized en+ru in `app/i18n.py`) instead of the generic
`err.invalid_request`. Tests: `tests/test_engine.py` — `test_cyber_refusal_gets_distinct_key`,
`test_non_cyber_refusal_gets_generic_refusal_key`, `test_real_invalid_request_still_generic`.

## OAuth token refresher wedged or looping — "sweep exceeded", missing heartbeat, or repeated 401s

The background refresher keeps the subscription OAuth credential fresh
(`app/core/token_refresh.py`). Three distinct log signals map to three different causes:

- **`token refresh: sweep exceeded …s (blocked DNS/socket?)`** — one sweep's blocking refresh ran
  past its deadline (a wedged resolver/socket). A single one is a transient blip (INFO); a repeat
  escalates to WARNING. **No action needed:** the loop abandons the wedged worker and recreates its
  single-thread executor, so the next sweep runs on a live pool and the wedge self-heals.
- **No `token refresh: alive — N sweeps done …` line for hours** — the liveness heartbeat (emitted
  every `OAUTH_REFRESH_HEARTBEAT_EVERY` sweeps, ~3 h) has stopped, so the loop itself is dead, not
  merely idle. Restart the unit: `systemctl restart claude-tg-bot`.
- **Every turn 401 + `token refresh: fail: refresh request rejected (… consecutive; manual re-login
  likely needed)`** — the `refresh_token` was revoked or rotated; the refresher cannot recover on
  its own. **Re-login on the host, THEN restart:** `claude setup-token` (never let
  `ANTHROPIC_API_KEY` into the env), then `systemctl restart claude-tg-bot`.
- **`token refresh: skip: no refresh token` / `skip: creds unreadable`** — the credential file no
  longer holds a usable login (a rejected refresh can leave it stripped). The broker then has no
  bearer to inject and answers `503`, which the CLI reports as a generic *"server-side issue"* — so
  the chat blames the model service while the real cause is the host login. Same fix: re-login,
  then restart.

The owner does not have to be reading the journal for any of this: a persistent failure is pushed
to their chat (🔴, repeated ~every 6 h while broken, 🟢 once it recovers), and a terminal
`no refresh token` / `creds unreadable` alerts on the first sweep. Cadence knobs:
`OAUTH_ALERT_AFTER_FAILS`, `OAUTH_ALERT_REPEAT_SWEEPS`. This is independent of the
`LOGIN_EXPIRY_WARN_DAYS` heads-up, which only counts down to the login's *nominal* expiry and
cannot see a login that dies early.

```bash
# Which of these is it? (timeouts, WARNING escalations, heartbeats)
journalctl -u claude-tg-bot | grep -E 'token refresh:' | tail -20
# Broker with no bearer at all (host login dead) — one line per blocked request:
journalctl -u claude-tg-bot | grep 'NO CREDENTIAL' | tail
# Confirm the broker still mints a working bearer: a 200 from 127.0.0.1:8789 = token good;
# a 401 = revoked login → re-login + restart.
```

---

## Sessions stuck on "Not named yet"

**Symptom.** `/sessions` lists used sessions still called *Not named yet* (or an older placeholder
such as *New chat*), typically one-line exchanges like "you there?" → "I'm here", or a photo sent
with a bare "what is this?".

**Mental model.** The Claude Code CLI writes a title only for a first prompt of 10+ characters, and
the earlier name fallback took only a "substantive" first message (10+ letters), so a short probe —
usually what an idle rotation's fresh session receives first — named nothing, while the empty-session
cleanup touched only sessions with zero requests. Now the first user message names the session as
typed (cut to the button width), the reply's topic covers a captionless photo, and a placeholder
session with nothing to name it by is archived once it is no longer current.

```bash
# Placeholder-named sessions with their request counts (read-only):
cd /root/Projects/tgbot && .venv/bin/python -c "
import sqlite3; from app import i18n
c = sqlite3.connect('file:bot.db?mode=ro', uri=True); names = sorted(i18n.placeholder_session_names())
q = 'SELECT thread_id, chat_id, name, (SELECT COUNT(*) FROM usage u WHERE u.thread_id=t.thread_id) '
q += 'FROM threads t WHERE name_auto=1 AND name IN (%s)' % ','.join('?' * len(names))
print(*c.execute(q, names).fetchall(), sep='\n')"
journalctl -u claude-tg-bot | grep 'untitled sweep' | tail
```

**Recovery.** Nothing manual: the sweep runs 2 minutes after start and daily, and on opening
`/sessions`, switching sessions and idle rotation. Archived sessions stay recoverable for the
archive-retention window.

---

## Table rows empty on iOS until the chat is reopened

**Symptom.** On the Telegram iOS client a streamed reply's table shows its frame (and maybe the
header) with empty rows; leaving the chat and coming back shows the data. Other clients are fine.

**Mental model.** An iOS client limitation: it builds a rich table's view once and reuses it as the
table grows in later draft frames without drawing the cells added since; the final message inherits
the draft's bubble. Details: [rich-message-spec.md](rich-message-spec.md).

**Recovery / workaround.** Reopen the chat. To avoid it for everyone, set
`DRAFT_HOLD_OPEN_TABLES=1` and restart: tables then appear in the draft only once complete (no
row-by-row animation).

---

## A new model is missing from `/model`, or turns fail right after a model release

**Symptom.** The picker lacks a just-released model, or a session on a family alias errors out.

**Mental model.** Models, their names and effort levels come from the Claude Code CLI. The bot runs
`claude update` once a day at `CLI_UPDATE_AT_UTC` (default 12:00 UTC), re-stages the jail copy, and
re-reads the catalog; idle clients then reconnect on the new binary, a busy one after its reply.
The Fable family never shows in the picker — it is withheld on purpose (see
[configuration.md](configuration.md), *Deliberate exceptions*).

```bash
/root/.local/bin/claude --version; /usr/local/bin/claude --version   # host vs jail copy
journalctl -u claude-tg-bot | grep -E 'Claude CLI|CLI model catalog|Staged sandbox|recycled' | tail
```

**Recovery.** Settings → Admin → 🔄 CLI update → 🔄 Check now (or `systemctl restart claude-tg-bot`,
which also re-stages the CLI and re-probes the catalog).

---

## Raw keys such as `admin.cli_btn` instead of labels in a menu

**Symptom.** A button or page shows a dotted identifier (`admin.cli_btn`, `admin.cli_title`)
instead of text.

**Mental model.** `i18n.t()` never raises: a key missing from `app/i18n.py` renders as the key
itself, so a code change that adds a lookup without its catalog row ships silently.

**Fast diagnosis.** `python -m pytest -q tests/test_i18n.py` —
`test_every_key_used_in_code_exists` lists every literal key the code looks up that the catalog
lacks.

**Recovery / fix in code.** Add the missing rows (`en` + `ru`) to `app/i18n.py` and restart. The
test keeps it from recurring.

## MAX side silent, or `certificate verify failed` in the journal

MAX is served by a long-poller next to the Telegram one; its failures only log and back off, so
the Telegram side keeps working while MAX is down.

```bash
# Is MAX enabled and authorized? (one line at startup; token never logged)
journalctl -u claude-tg-bot -n 300 | grep -E 'MAX: (authorized|polling started|get_updates failed|startup get_me)'
# TLS trust: the API host chains to the Russian Trusted Root CA bundled in deploy/certs/.
openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru \
  -CAfile deploy/certs/russian_trusted_root_ca.pem </dev/null 2>/dev/null | grep 'Verify return'
```

- `certificate verify failed` → the bundle is missing or `MAX_CA_BUNDLE` points at the wrong
  file; `Verify return code: 0 (ok)` above means the bundle is right.
- `401` on `get_me` → the token is wrong or was regenerated in the bot's MAX settings.
- A user writes on MAX and nothing happens → they are not allowed yet: the owner's Telegram chat
  received the access request with the user's internal id (`1000000…`) and Allow buttons.
- Updates replayed after a restart → the kv `max_marker` was lost; the platform re-delivers
  unacknowledged updates once. Harmless.
- A "Thinking…" message that never resolves → the turn ended without a message to that chat
  (the same root causes as the Telegram indicator above); it is deleted or reused on the next
  reply and dropped after 15 minutes.
