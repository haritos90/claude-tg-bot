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

## How THIS bot maps onto the spec

- `rich_message.py` — `SendRichMessage` / `EditRichMessage` / `SendRichMessageDraft`
  (`TelegramMethod`s); `rich_message` is an `InputRichMessage` dict (we pass `{"markdown": …}`
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

**How THIS bot uses it now (#239):** `streamer.py` sends
`SendRichMessageDraft({"html": "<tg-thinking>Thinking…</tg-thinking>"})` (constant
`_THINKING_HTML`) as the initial `start()` placeholder and on the segment reset between tool
calls. It is static "Thinking…" — we do NOT yet drive its `text` from the live tool activity,
and we do not add custom emoji or localize it (the `Streamer` has no `lang`).

**Potential (not done):** route the agent's tool-status / phase into the `<tg-thinking>` `text`
so the block shows the live action (and AIActions emoji), instead of (or alongside) the separate
"Working…" control plate — a native, self-cleaning "what the agent is doing" line. Keep it
DRAFT-ONLY; finish() must stay `{"markdown": full_text}` with no thinking block.
