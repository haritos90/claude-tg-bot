# markup.md — message-formatting specification

Specification of how the bot renders outbound Telegram messages: the two rendering
paths, the markdown→HTML conversion contract, the native rich tag set, and the
size/splitting rules. Companion to **[menu.md](menu.md)** (commands / settings
structure).

> Telegram reference: **Rich message formatting options** —
> <https://core.telegram.org/bots/api#rich-message-formatting-options>
> (Bot API **10.1**, 2026-06-11, added `sendRichMessage` and the rich tag set.)

---

## 1. Rendering paths

The bot has two mechanisms for formatted output. **Path B (native rich) is the
default for every reply and every menu;** Path A (classic HTML) is the fallback.

### Path B — native rich messages (`sendRichMessage`, #164/#169/#172/#173)

`sendRichMessage` takes an `InputRichMessage` — a single `markdown` or `html` string
— and the client renders the full rich tag set: headings, paragraphs, nested lists,
checklists, block quotes, real side-scrolling `<table>`s, and code blocks. aiogram
3.28 ships no binding, so the methods are declared by hand in **`rich_message.py`**
as `TelegramMethod` subclasses and invoked via `await bot(SendRichMessage(...))`:

| Class | `__api_method__` | Use |
|---|---|---|
| `SendRichMessage` | `sendRichMessage` | send a rich message (optionally with `reply_markup`) |
| `SendRichMessageDraft` | `sendRichMessageDraft` | stream a partial, animated rich draft (private chats) |
| `EditRichMessage` | `editMessageText` (+ `rich_message`) | edit a message to rich content in place (#173) |

Input-field selection:
- **`markdown`** — used for model replies (raw model Markdown is passed straight
  through; the client renders structure natively).
- **`html`** — used for bot-authored surfaces whose text is already valid Telegram
  HTML: command replies (`reply` → `reply_rich_html`) and the inline-keyboard menus
  (`_send_menu` / `_edit_menu`, #173).

### Path A — classic HTML (`parse_mode="HTML"`)

`markup.md_to_html()` converts a safe Markdown subset to Telegram HTML, sent with
`send_message(..., parse_mode="HTML")`. This path supports only the *classic* tag set:

`<b> <i> <u> <s> <code> <pre> <a> <tg-spoiler> <blockquote>` (+ `<blockquote expandable>`).

Path A is reached only as a **fallback** when a `sendRichMessage` / `editMessageText`
rich call raises, so a message or menu is never lost.

---

## 2. Whole-reply rendering

Every model reply is sent as **one** native rich message. `streamer._commit` calls
`streamer._commit_rich_markdown`, which passes the reply's raw Markdown to
`sendRichMessage({"markdown": …})`; the client renders headings, lists, tables,
quotes, code and math natively, with no client-side char splitting. While generating,
the reply is streamed already-formatted via `sendRichMessageDraft` (#172); long output
collapses behind a client-side "show more" control.

**Code blocks go through the rich path like everything else.** A fenced block
(` ```lang `) maps to `RichBlockPreformatted`. The API accepts it, but the current
Telegram client renders it as **plain monospace** — no language label, no syntax
styling, no copy button (#174). This is a client-side gap, not a bot-side choice:
when the client styles `RichBlockPreformatted`, code begins rendering as a full code
block with **no change here**. Sending the whole reply as one rich message keeps the
font consistent across prose, tables and code, rather than splitting a reply into
mixed rich + classic bubbles.

A split-by-segment alternative — prose/tables as rich, each code block as a classic,
copyable `<pre><code>` bubble — is implemented in `streamer._commit_mixed` (with
`markup.split_code_blocks`) but **un-called**. It can be re-enabled in
`streamer._commit` if the rendering trade-off is revisited.

### Markdown → classic HTML (Path A conversion table)

`md_to_html` strategy (`markup.py`): escape everything first, then re-apply a small
safe subset over the already-escaped text, so model/user text can never inject tags.
Order: stash code fences → inline code → `[text](url)` links and ATX `#` headers →
bold/italic/strikethrough/spoiler → blockquotes → LaTeX→Unicode → un-stash. On any
error it returns a fully-escaped plain string (a message is never dropped for bad HTML).

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
| LaTeX (`\frac`, `$…$`, `x^2`) | Unicode (½, ×, x²) | #51; Telegram cannot render LaTeX |

Table helpers (used by the `/userstats` table and as the html-table builder):
- `markup.split_rich_tables(text)` → plain-text runs + `RichTable` objects (per-column
  alignment from the `:--:` separator).
- `markup.table_to_rich_html(rows, aligns)` → `<table bordered striped>` with `<th>`
  header cells, `align=…`, inline `<b>`/`<code>` inside cells.
- `streamer._send_rich(table, silent)` → html-table send with a `<pre>`-grid fallback.

---

## 3. Long messages and splitting

No client-side splitting is required: a single rich message holds far more than the
classic 4096-char limit, and long output collapses behind a client "show more"
control. The only size fallback is the **`.md` document** for very large output
(`markup.should_send_as_file`, `FILE_THRESHOLD = SAFE_LIMIT * 3`), and it triggers
only if the rich send itself fails.

The earlier PNG table path (`table_image.py`, `split_image_tables`) and the `<pre>`
monospace grid (`_render_table_pre` / `_tables_to_pre`) are retained but commented out.

---

## 4. Native rich tag catalog

Tags `sendRichMessage` (Path B) can render. Status legend:
**✅ emitted by the bot** · **🟡 renders via Path B but not auto-emitted** ·
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
| `<pre>` / `<pre><code class="language-…">` | code block | ✅ via rich (renders plain monospace pending client styling, #174); Path A renders a full classic code block |
| `<footer>` | footer text | 🟡 |
| `<hr/>` | divider | 🟡 |
| `<ul><li>` | unordered list | 🟡 (Path A keeps `- ` as text) |
| `<ol><li>` (+ `start`/`type`/`reversed`/`value`) | ordered list | 🟡 |
| `<li><input type="checkbox" [checked]>` | checklist | 🟡 |
| `<blockquote>` (+ `<br>`, `<cite>`) | block quote | ✅ |
| `<aside>` (+ `<cite>`) | pull quote | 🟡 |
| `<details>`/`<summary>` (+ `open`) | collapsible | 🟡 |
| `<table>` (`bordered`/`striped`, `<caption>`, `<th>`, `colspan`/`rowspan`, `align`/`valign`) | table | ✅ (#164) |
| `<tg-math-block>` | display math | 🟡 |

### Media (require a real URL or uploaded file)
| Tag(s) | Meaning | Status |
|---|---|---|
| `<img>` | photo | 🟡 |
| `<video>` / `<audio>` | video / audio / voice | 🟡 |
| `<figure>`/`<figcaption>` | captioned media | 🟡 |
| `<tg-map lat long zoom>` | map (no file needed) | 🟡 |
| `<tg-collage>` / `<tg-slideshow>` | grouped media | 🟡 |

---

## 5. File map

| Concern | Location |
|---|---|
| Markdown → classic HTML | `markup.md_to_html` |
| Escaping | `markup.escape_html` |
| Native table split / render | `markup.split_rich_tables`, `markup.table_to_rich_html`, `markup.RichTable` |
| Rich method bindings | `rich_message.py` (`SendRichMessage`, `SendRichMessageDraft`, `EditRichMessage`) |
| Whole-reply rich commit + fallback | `streamer._commit`, `streamer._commit_rich_markdown`, `streamer._commit_mixed` |
| Native-table send + fallback | `streamer._send_rich`, `streamer._build_sendables` |
| Rich menu open / in-place edit (#173) | `handlers._send_menu`, `handlers._edit_menu` |
| PNG fallback (retained, commented) | `table_image.py`, `markup.split_image_tables` |
| Commands & settings structure | **[menu.md](menu.md)** |

See also the **Message formatting** section of the [README](README.md).
