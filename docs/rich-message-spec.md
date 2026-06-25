# Rich message, draft & table — authoritative spec (#237)

Ground truth for streaming + sending rich messages, extracted **verbatim** from the
official Telegram Bot API docs (<https://core.telegram.org/bots/api>) on 2026-06-19.
These methods are POST-cutoff (Bot API 10.1, 2026-06-11) — **never reason about them from
memory**; re-verify with the `/verify-rich-draft` command, which re-fetches the live docs
and can live-send a test to the owner.

Relevant doc sections: *Rich Message Formatting Options*, *sendRichMessage*,
*sendRichMessageDraft*, *InputRichMessage*, *RichBlockTable* / *RichBlockTableCell*,
*RichText*.

## The two-call streaming contract

- **`sendRichMessageDraft`** — *"stream a partial rich message to a user while the message
  is being generated. Note that the streamed draft is ephemeral and acts as a temporary
  30-second preview — once the output is finalized, you must call `sendRichMessage` with the
  complete message to persist it."* Returns `True`.
  - `chat_id` (Integer, required) — **private chat only**.
  - `draft_id` (Integer, required) — **must be non-zero**. *"Changes to drafts with the same
    identifier are animated."* (So reuse ONE id per chat and Telegram animates the appended
    text between successive drafts.)
  - `rich_message` (InputRichMessage, required) — the partial message.
  - `message_thread_id` (optional).
- **`sendRichMessage`** — persists the final message. `chat_id`, `rich_message` (required);
  `disable_notification`, `protect_content`, `message_thread_id`, … (optional). Returns the
  sent `Message`.

## InputRichMessage

> *Describes a rich message to be sent. **Exactly one of the fields `html` or `markdown`
> must be used.***

- `html` (String) — content described using **Rich HTML**.
- `markdown` (String) — content described using **Rich Markdown** (GFM-compatible).
- `is_rtl` (Boolean, optional) — show right-to-left.
- `skip_entity_detection` (Boolean, optional) — skip auto-detect of URLs/mentions/etc.

## How a TABLE is written

A table can be expressed in EITHER form (server converts both to a `RichBlockTable`):

### Markdown form (GFM) — what this bot streams + persists

```
| Header 1 | Header 2 |
|:---------|:--------:|
| left     | center   |
```

- Header row, then a **separator row** (`|:---|:--:|` — alignment via leading/trailing `:`),
  then data rows. This is standard GFM.
- **A table is only valid once the header + separator (+ ≥0 complete rows) exist.** A
  half-typed row or a partial separator is NOT a valid table → Telegram renders the header
  line alone. THIS is the streaming trap (#226): the draft must only ever carry COMPLETE
  rows. The fix (#237, `markup.clip_partial_table`) clips the in-progress trailing row so
  each draft is a valid prefix and the table grows row-by-row with no snap.
- *"Table cells can contain only inline formatting"* (bold, code, `<sup>`, `<tg-spoiler>`,
  …) — no block elements inside a cell.

### HTML form

```
<table><tr><th>Header 1</th><th>Header 2</th></tr><tr><td>Value 1</td><td>Value 2</td></tr></table>
<table bordered striped><caption>…</caption>…</table>
```

- `<table>` with optional `bordered` / `striped` attributes and `<caption>`; `<th>` header
  cells, `<td>` data cells; cell `align` (left/center/right), `valign`, `colspan`, `rowspan`.

### Structured block (for reference — not used by this bot)

- **RichBlockTable**: `type` = `"table"`, `cells` = Array of Array of RichBlockTableCell,
  `is_bordered` (True, opt), `is_striped` (True, opt), `caption` (RichText, opt).
- **RichBlockTableCell**: `text` (RichText, opt — omit ⇒ invisible cell), `is_header` (True,
  opt), `colspan`/`rowspan` (Integer, opt), `align` (left/center/right), `valign`
  (top/middle/bottom).

## Rich message limits

- ≤ 32768 UTF-8 chars total. ≤ 500 blocks (incl. nested blocks, list items, **table rows**,
  quotes, details). ≤ 16 nesting levels. ≤ 50 media attachments. **≤ 20 columns in a table.**
- Media is a separate block (HTTP/HTTPS URLs only); not inside table cells.

## Line breaks, paragraphs & code blocks — VERIFIED (2026-06-22, via parsed `rich_message.blocks`)

The two fields handle newlines DIFFERENTLY. Verified empirically by sending each form and
reading the server-parsed `result.rich_message.blocks` (ground truth — stronger than the prose
docs, which truncate in a fetch). A single `\n` is NOT honoured as a line break in either rich
field (a frequent misconception, and the distinction the #310 migration hinges on) — see the
per-field table below.

| Source text | Rich HTML → parsed | Rich Markdown → parsed |
|---|---|---|
| single `\n` | collapsed to a SPACE (one paragraph) | soft break = SPACE (one paragraph) |
| `<br>` (html) / `  \n` two trailing spaces (md) | `\n` INSIDE one paragraph | `\n` INSIDE one paragraph |
| blank line `\n\n` | collapsed to a SPACE (one paragraph) | SEPARATE `paragraph` blocks |

- **Rich HTML collapses ALL newlines** (single AND double) to spaces, exactly like real HTML —
  a visible line break needs `<br>`; paragraph separation needs block tags. This is WHY the menu
  path runs `\n`→`<br>` (#202): without it every line collapses onto one wrapped line.
- **Rich Markdown (GFM/CommonMark):** a single `\n` is a SOFT break (renders as a space); a
  blank line `\n\n` is a PARAGRAPH break; two trailing spaces + `\n` is a HARD break.
- **1:1 line-break equivalence (verified `blocks ==` equal):** HTML `<br>` and markdown `  \n`
  (two trailing spaces) parse to the IDENTICAL block (`{"type":"paragraph","text":"A\nB\nC"}`).
  So a `\n`→`<br>` HTML string maps to a `\n`→`  \n` markdown string — NOT "drop the `<br>`,
  markdown honours newlines" (it does NOT honour a single `\n`). Block constructs (lists `- x`,
  tables, `` ```fences ``, headings) break on their own and need no hard break.

### Code blocks (`RichBlockPreformatted`, parsed `"type":"pre"`)

- `<pre><code class="language-python">…</code></pre>` (html) and `` ```python … ``` `` (markdown)
  BOTH parse to the SAME block `{"type":"pre","text":…,"language":"python"}` — the `language`
  IS captured in both forms (verified). Inline `<code>` / backticks → `{"type":"code",…}`
  (RichTextCode). So html and markdown are byte-identical for code.
- Telegram CLIENTS render `pre` as PLAIN MONOSPACE; syntax-HIGHLIGHTING (colourisation) is a
  per-client decision and is NOT applied in (at least) the macOS Desktop client even though
  `language` is set. "No colours" is therefore a client rendering choice, NOT a bot/API bug, and
  is identical across the html/markdown fields. Re-verify with the
  parsed-blocks probe (`sendRichMessage` → read `result.rich_message.blocks`).

## How THIS bot maps onto the spec

- `rich_message.py` — `SendRichMessage` / `EditRichMessage` / `SendRichMessageDraft`
  (`TelegramMethod`s); `rich_message` is an `InputRichMessage` dict (the bot passes `{"markdown": …}`
  for replies/drafts, `{"html": …}` for menus and the native-table fallback `table_to_rich_html`).
- `streamer._render_draft` — `SendRichMessageDraft({"markdown": frontier})`, one fixed
  `_DRAFT_ID`, ~5/sec. **Must send only valid markdown** → `markup.clip_partial_table`
  trims the in-progress table row (#237).
- `streamer._commit_rich_markdown` (finish) — `SendRichMessage({"markdown": full_text})`:
  the WHOLE reply as one rich message (#176). SAME renderer as the draft, so a complete
  table renders identically; the draft is just an earlier valid prefix of it.
- `markup.table_to_rich_html` — builds the `<table>` HTML form (the #164 native-table path /
  `_send_rich` fallback).

**Invariant:** the draft and the final message use the SAME `{"markdown"}` representation, so
streaming = sending a growing valid PREFIX. If a table looks wrong mid-stream, the draft is
carrying invalid GFM (a partial row/separator) — fix the prefix, do NOT switch representation
(no `<pre>` grid, no placeholder — those were the rejected #226 attempts).

## `<tg-thinking>` — the "Thinking…" block (RichBlockThinking, #239)

What the docs say (verbatim): *"A block with a 'Thinking…' placeholder, corresponding to the
custom HTML tag `<tg-thinking>`. The block may be used **only in `sendRichMessageDraft`**,
therefore it can't be received in messages."* Fields: `type` = `"thinking"`, `text` (RichText —
custom emoji from t.me/addemoji/AIActions are recommended). Used inline in a draft as
`<tg-thinking>Thinking…</tg-thinking>`.

**Custom (premium) emoji in the indicator (#323).** The 💭 / 🔎 icons become CUSTOM animated emoji
when the bot is allowed to send them — which needs the bot OWNER to have Telegram Premium
(auto-detected from the owner's `from_user.is_premium` → `streamer.set_owner_premium`) OR the bot to
own a Fragment username; viewers NEVER need Premium (everyone sees them animated). Ids are
configured via the `THINKING_EMOJI_IDS` env (`think:<custom_emoji_id>,search:<id>` — e.g. from the
AIActions pack); empty → plain unicode (default, no change). `streamer._emoji(uni, role)` emits
`<tg-emoji emoji-id="…">uni</tg-emoji>` only when (owner-premium AND an id is set); the `uni` is the
required fallback. A draft the server rejects self-heals back to unicode for the turn. NOTE (not yet
verified live): the owner-Premium pathway is documented for *sent messages*; whether it also covers
custom emoji inside a DRAFT (`sendRichMessageDraft`) needs a live check with a Premium owner — the
Fragment-username pathway is the safe one.

**Why Telegram added it / what it affects.** It is the OFFICIAL primitive for the "AI is
working" state during streaming. Unlike plain text, the client renders it as a distinct,
animated *reasoning/working* indicator (the ChatGPT-style "Thinking…" shimmer), and because it
is **draft-only it can never persist into chat history** — the working state auto-vanishes when
the turn is finalized with `sendRichMessage`. So it lets an AI bot show *what it is doing right
now* (reasoning, before/between visible output) as a first-class, self-cleaning UI element
rather than a fake placeholder message the bot would have to delete.

**What its `text` is for.** The block carries arbitrary RichText, so the indicator can reflect
the CURRENT phase — "Thinking…", "Reading files…", "Running `pytest`…", "Searching the web…" —
optionally with the AIActions custom emoji. Update it (reuse the same `draft_id`) as the agent
moves between phases; replace it with real content once output starts.

**How THIS bot uses it (#240/#294/#319):** `start()` sends
`SendRichMessageDraft({"html": "<tg-thinking>…</tg-thinking>"})` and the animation loop
(`streamer._render_draft`, ~0.2 s/tick) keeps repainting it until real output starts. The inner
text is, in priority order: the model's live REASONING tail (extended thinking) → a SEARCH-themed
rotating gerund (`stream.searching_words`, 🔎) while a web search/fetch is in flight → a fixed
tool phase ("📖 Reading `sessions.py`") for other tools → otherwise a generic rotating gerund
(`stream.thinking_words`, 💭). All localized to the user's language.

### Animation & "still-working" feedback — the hard constraints (#319)

Only the `<tg-thinking>` block streamed as a rich DRAFT animates smoothly — Telegram drives the
token-by-token motion client-side. Everything else is effectively STATIC:

- **Regular message edits** (`EditMessage` / `EditRichMessage`) are throttled to roughly ONE
  update per second. That's fine for an occasionally-updated SIDE message (e.g. the TodoWrite
  task card) but NOT usable for animation or — especially — streaming generated text. Stream
  text and any "alive" animation through the DRAFT, never through edits.
- **A fixed string** in the thinking block (e.g. a static "🌐 Searching the web…" phase) does NOT
  animate — only a CHANGING draft does. A long, silent operation therefore needs the placeholder
  to keep CHANGING (a rotating gerund), not a frozen label.

Rule: whenever the bot is working and NOT streaming text, it MUST show an animating
`<tg-thinking>` draft — it is the only non-verbal "I'm still alive" signal. During a web search
the placeholder rotates the search-themed subset (`stream.searching_words`, 🔎) so the motion
reads as info-gathering — the thinking tag ALONE, no separate "sources" card (#321: a card
listing the queries was tried and removed — it read as clutter and mislabelled the queries as
"sources", which the model already cites itself as links in the answer).
Keep the block DRAFT-ONLY; `finish()` must stay `{"markdown": full_text}` with no thinking block.

## Math / formulas — `mathematical_expression` (#297)

Telegram renders LaTeX math natively (Bot API 10.1: `RichTextMathematicalExpression` inline,
`RichBlockMathematicalExpression` block). **Verified live** against the API on 2026-06-21 (a
`sendRichMessage` probe + the returned parsed `rich_message` JSON, confirmed on-device) — the
exact INPUT→block mapping in the **Rich Markdown** form the bot uses:

| Input (in `{"markdown"}`) | Parses to | Render |
|---|---|---|
| `$e^{i\pi}+1=0$` | inline `{"type":"mathematical_expression","expression":"e^{i\\pi}+1=0"}` | ✅ inline formula |
| `$$\int_0^1 x^2\,dx$$` | block `mathematical_expression` | ✅ centered block formula |
| ```` ```math … ``` ```` (fenced) | block `mathematical_expression` | ✅ (equivalent to `$$…$$`) |
| `\(…\)` / `\[…\]` | plain paragraph text | ❌ NOT parsed — shown literally |
| HTML `<math>…</math>` | plain text (tag stripped) | ❌ — in the HTML form use `<tg-math>…</tg-math>` |

- The `expression` is **standard LaTeX** (`\frac`, `\sqrt`, `\sum`, `\int`, `^`, `_`, Greek, …).
- The bot streams + persists as `{"markdown"}` (#176), so `$…$` / `$$…$$` pass straight through
  on BOTH the draft and final send — no special handling needed. The classic-HTML fallback
  (`markup._latex_to_unicode`, #51) still degrades math to Unicode only when a rich send fails.
- The chat prompt (`engine.CHAT_SYSTEM_PROMPT`) and `app/core/agent_context.md` instruct the model to
  emit `$…$` / `$$…$$` and to escape a literal dollar as `\$`.
- **Streaming note:** an unclosed `$`/`$$` at the draft frontier renders as literal text until
  it closes, then snaps to the formula — the SAME behavior as a half-typed `**bold**`, and
  harmless (it does NOT break sibling blocks the way a partial table did, #237), so no
  clip-partial-math step is needed. Re-verify with `deploy/verify-rich-draft.py --math`.
