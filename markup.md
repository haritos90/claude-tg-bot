# markup.md — message formatting in the bot

How the bot turns a model's reply (Markdown) into formatted Telegram messages, the
full catalog of Telegram rich-formatting tags, and exactly which ones the bot emits
today. Companion to **[menu.md](menu.md)** (commands / settings structure).

> Telegram reference: **Rich message formatting options** —
> <https://core.telegram.org/bots/api#rich-message-formatting-options>
> (Bot API **10.1**, 2026‑06‑11: added `sendRichMessage` + the rich tag set.)

---

## Two rendering paths

The bot has **two** ways to put formatting on screen. Most replies use Path A; tables
use Path B.

### Path A — classic HTML (`parse_mode="HTML"`)
The default. The model writes Markdown; `markup.md_to_html()` converts a **safe subset**
to Telegram HTML and the text is sent with `send_message(..., parse_mode="HTML")` (or
streamed via message drafts). This path supports only the *classic* tag set:

`<b> <i> <u> <s> <code> <pre> <a> <tg-spoiler> <blockquote>` (+ `<blockquote expandable>`).

`md_to_html` strategy (see `markup.py`): **escape everything first**, then re-apply a
small, safe subset by operating on the already-escaped text — so user/model text can
never inject rogue tags. Order: stash code fences → inline code → `[text](url)` links
and ATX `#` headers → bold/italic/strikethrough/spoiler → blockquotes → LaTeX→Unicode →
un-stash. On any error it falls back to a fully-escaped plain string (a message is
never dropped for bad HTML).

Markdown the bot converts on Path A:

| Markdown | → Telegram | Notes |
|---|---|---|
| `**bold**` / `__bold__` | `<b>` | |
| `*italic*` / `_italic_` | `<i>` | |
| `~~strike~~` | `<s>` | guarded vs `~~~` code fences |
| `` `code` `` | `<code>` | stashed so emphasis skips it |
| ```` ```lang ... ``` ```` | `<pre><code class="language-…">` | language preserved |
| `> quote` | `<blockquote>` | ≥10 lines → `<blockquote expandable>` |
| `\|\|spoiler\|\|` | `<tg-spoiler>` | conservative (non-space edges) |
| `[text](url)` | `<a href>` | |
| `# Heading` (ATX) | bold line | classic HTML has no `<h1>` |
| `- item` / `1. item` | left as text | classic HTML has no `<ul>/<ol>` |
| LaTeX (`\frac`, `$…$`, `x^2`) | Unicode (½, ×, x²) | `#51`; Telegram can't render LaTeX |

### Path B — native rich messages (`sendRichMessage`, #164)
Bot API 10.1 added `sendRichMessage`, whose `InputRichMessage` takes a single **`html`**
(or `markdown`) string that renders the **full** rich tag set — including real `<table>`s
that the client lays out and **side-scrolls**. aiogram 3.28 has no binding, so we declare
the method by hand in **`rich_message.py`** (`SendRichMessage(TelegramMethod[Message])`,
`__api_method__="sendRichMessage"`), called as `await bot(SendRichMessage(...))`.

Since #169 the bot uses Path B for **the whole reply**: `streamer._commit_rich_markdown`
passes the model's raw Markdown straight to `sendRichMessage` as
`rich_message={"markdown": …}`, and Telegram renders headings, lists, tables, code, quotes
etc. natively. The legacy Path-A chunk/split/table-bubble code is now only the **fallback**
(used if a `sendRichMessage` call fails — a reply is never lost).

Table helpers (still used by the `/userstats` table and as the html-table builder):
- `markup.split_rich_tables(text)` → plain-text runs + `RichTable` objects (per-column
  alignment from the `:--:` separator).
- `markup.table_to_rich_html(rows, aligns)` → `<table bordered striped>` with `<th>`
  header cells, `align=…`, inline `<b>`/`<code>` kept inside cells.
- `streamer._send_rich(table, silent)` → html-table send with a `<pre>`-grid fallback.

### Long messages & splitting (#169)
**No splitting is needed.** A rich message holds far more than the classic 4096-char
limit: a ~9.3k-char test rendered as a single message showing **~22 paragraphs**, with a
**“show more”** button revealing the rest. So neither the old char-limit chunking nor the
table-into-separate-bubbles split is used on the happy path. The only size fallback kept is
the **`.md` document** for truly huge output (`markup.should_send_as_file`,
`FILE_THRESHOLD = SAFE_LIMIT*3`), and that only triggers if the rich send itself fails.

The earlier PNG path (`table_image.py`, `split_image_tables`) and the `<pre>` grid
(`_render_table_pre`/`_tables_to_pre`) are **kept but commented out** (revert-friendly).

---

## Full Telegram rich-formatting catalog

Everything `sendRichMessage` (Path B) can render. Status legend:
**✅ emitted by the bot today** · **🟡 renders via Path B but not auto-emitted** ·
**🖥 Path A only**.

### Inline text
| Tag(s) | Meaning | Status |
|---|---|---|
| `<b>` / `<strong>` | bold | ✅ |
| `<i>` / `<em>` | italic | ✅ |
| `<u>` / `<ins>` | underline | 🖥 (no Markdown source) |
| `<s>` / `<strike>` / `<del>` | strikethrough | ✅ |
| `<code>` | inline fixed-width | ✅ |
| `<mark>` | marked / highlight | 🟡 |
| `<sub>` / `<sup>` | sub/superscript | 🟡 (LaTeX→Unicode covers most cases on Path A) |
| `<tg-spoiler>` | spoiler | ✅ |

### Links & entities
| Tag(s) | Meaning | Status |
|---|---|---|
| `<a href="https://…">` | inline URL | ✅ |
| `<a href="mailto:…">` | e-mail | 🟡 (auto-detected too) |
| `<a href="tel:…">` | phone | 🟡 |
| `<a href="tg://user?id=…">` | user mention | 🟡 |
| `<a href="#anchor">` + `<a name>` | in-document link | 🟡 |
| `<tg-reference name>` + `<a href="#…">` | footnote/reference | 🟡 |
| `<tg-emoji emoji-id>` | custom (premium) emoji | 🟡 |
| `<tg-time unix format>` | localized time | 🟡 |
| `<tg-math>` | inline math | 🟡 |
| auto: `#hashtag $CASHTAG @user /cmd`, card, phone, URL | entity detection | ✅ (Telegram auto-detects) |

### Blocks
| Tag(s) | Meaning | Status |
|---|---|---|
| `<h1>`…`<h6>` | headings | 🟡 (Path A renders `#` as bold) |
| `<p>` | paragraph | 🟡 |
| `<pre>` / `<pre><code class="language-…">` | code block | ✅ **classic only** — see ⚠ below (rich = plain monospace) |
| `<footer>` | footer text | 🟡 |
| `<hr/>` | divider | 🟡 |
| `<ul><li>` | unordered list | 🟡 (Path A keeps `- ` as text) |
| `<ol><li>` (+ `start`/`type`/`reversed`/`value`) | ordered list | 🟡 |
| `<li><input type="checkbox" [checked]>` | checklist | 🟡 |
| `<blockquote>` (+ `<br>`, `<cite>`) | block quote | ✅ |
| `<aside>` (+ `<cite>`) | pull quote | 🟡 |
| `<details>`/`<summary>` (+ `open`) | collapsible | 🟡 |
| `<table>` (`bordered`/`striped`, `<caption>`, `<th>`, `colspan`/`rowspan`, `align`/`valign`) | **table** | ✅ (#164) |
| `<tg-math-block>` | display math | 🟡 |

### Media (need a real URL or uploaded file)
| Tag(s) | Meaning | Status |
|---|---|---|
| `<img>` | photo | 🟡 |
| `<video>` / `<audio>` | video / audio / voice | 🟡 |
| `<figure>`/`<figcaption>` | captioned media | 🟡 |
| `<tg-map lat long zoom>` | map (no file needed) | 🟡 |
| `<tg-collage>` / `<tg-slideshow>` | grouped media | 🟡 |

> A one-shot showcase of every category above was sent to the owner via `sendRichMessage`
> on 2026‑06‑16 — all 13 category messages were accepted by the live API.

---

## Whole-reply rendering — rich vs classic, per reply (#169 / #172)

`InputRichMessage` accepts a **`markdown`** field, so a reply can be sent through
`sendRichMessage({"markdown": …})` and the model's headings, nested lists, checklists,
tables, quotes and math render **natively**, with no splitting (long output collapses
behind a "show more" button).

### ⚠ The one exception: CODE blocks → we use LEGACY (classic), verified 2026‑06‑17
There **is** a documented "correct" way to do a code block in a rich message —
**`RichBlockPreformatted`**, written as ```` ```lang `````  (markdown) or
`<pre><code class="language-…">` (html). The API **accepts** it, **but the Telegram
client does not render it as a real code block yet** — it shows only as **plain
monospace**: no language label, no syntax styling, no copy button. Tested every variant
(standalone, blank-line-separated, markdown vs html); all are plain monospace.

So for code we fall back to the **LEGACY / classic** path (`send_message` with
`<pre><code class="language-…">`), which **is** a proper, fully-copyable code block
(and copy works inline, so no per-block splitting needed). This is a Telegram-side gap,
not a bug here — when their client styles `RichBlockPreformatted` properly, drop the
`"```"` guards in `streamer._commit` / `_commit_rich_markdown` / `_render_draft` and
code goes through rich too (TODO #174).

### The bot sends the WHOLE reply as ONE rich message (`streamer._commit_rich_markdown`)
Owner decision (2026-06-17): one consistent rich message beats splitting. So every reply —
prose, tables, lists, headings **and code** — goes through `sendRichMessage({"markdown":…})`,
streamed already-formatted via `sendRichMessageDraft` (#172), long output behind "show more".

The single caveat: **code renders as plain monospace** in rich (no language label / copy),
because the client doesn't style `RichBlockPreformatted` yet (#174). The owner prefers that
to splitting a code reply into rich+classic bubbles — and when Telegram styles code in rich,
it starts rendering properly with **no code change** here.

> The split-by-segment alternative — non-code runs as RICH, each code block as a CLASSIC
> `<pre><code>` (a real, copyable code block) — is implemented and KEPT but **un-called**
> (`streamer._commit_mixed` + `markup.split_code_blocks`). Flip the two back in
> `streamer._commit` if that preference ever changes.

Known trade-off (accepted): rich body text renders **slightly larger** than classic — the
reason owner-sent messages once looked bigger than the bot's; now every reply is rich, so
it's consistent.

---

## File map

| Concern | Location |
|---|---|
| Markdown → classic HTML | `markup.md_to_html` |
| Escaping | `markup.escape_html` |
| Native table split / render | `markup.split_rich_tables`, `markup.table_to_rich_html`, `markup.RichTable` |
| `sendRichMessage` binding | `rich_message.py` |
| Native-table send + fallback | `streamer._send_rich`, `streamer._build_sendables` |
| PNG fallback (kept, commented) | `table_image.py`, `markup.split_image_tables` |
| Commands & settings structure | **[menu.md](menu.md)** |

See also the **Message formatting** section of the [README](README.md).
