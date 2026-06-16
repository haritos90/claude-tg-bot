"""Telegram formatting helpers.

Telegram's hard limit is 4096 characters per message; we use a safe limit of
3900 to leave room for HTML entities and minor overhead.

Public surface (callers in streamer.py / handlers.py depend on these):
  - escape_html(s) -> str
  - md_to_html(text) -> str
  - split_message(text, limit=3900) -> list[str]
  - should_send_as_file(text) -> bool
  - as_document(text, filename) -> aiogram BufferedInputFile
"""

from __future__ import annotations

import re

from aiogram.types import BufferedInputFile

SAFE_LIMIT = 3900
# Telegram's hard per-message ceiling. split_markdown sizes by RAW length, but
# md_to_html escaping/markup can expand a chunk past this; render_within_limit
# re-splits so a rendered message never exceeds it (and gets silently dropped).
HARD_LIMIT = 4096
# Above this length the caller may prefer to send a .md document instead of
# spamming the chat with many chunks.
FILE_THRESHOLD = SAFE_LIMIT * 3


# --------------------------------------------------------------------------- #
# Escaping
# --------------------------------------------------------------------------- #
def escape_html(s: str) -> str:
    """Escape the three characters Telegram HTML treats specially.

    Order matters: ``&`` must be escaped first so we do not double-escape the
    ``&`` we introduce for ``<`` and ``>``.
    """
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# --------------------------------------------------------------------------- #
# Markdown -> Telegram HTML
# --------------------------------------------------------------------------- #
# Telegram HTML supports: b, i, u, s, code, pre, a, tg-spoiler, and blockquote
# (including <blockquote expandable>). See the README "Message formatting" section
# and the Telegram docs linked there for the full tag list + nesting rules.
# Strategy: HTML-escape EVERYTHING first, then re-apply a small, safe subset of
# Markdown by operating on the already-escaped text. Because the source has been
# escaped, any user-supplied ``<`` / ``>`` / ``&`` cannot form rogue tags; the
# only tags present are the ones we deliberately insert below.

_FENCE_RE = re.compile(
    r"```[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)
# Same as _FENCE_RE for ~~~ fences (some models emit these instead of ```).
_FENCE_TILDE_RE = re.compile(
    r"~~~[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)~~~",
    re.DOTALL,
)
_FENCE_NOLANG_RE = re.compile(r"```(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_USCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL)
_ITALIC_USCORE_RE = re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL)
# [text](url) links and ATX (#..) headers; placeholder token for the stash.
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)\s*\)")
_ATX_HEADER_RE = re.compile(r"(?m)^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_PH_RE = re.compile(r"\x00PH(\d+)\x00")
# A markdown table separator row: |---|:--:|---| (the line under the header).
_TABLE_SEP_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$"
)

# --- modern rich formatting (Telegram "rich message formatting options") ------ #
# ~~strikethrough~~ (GitHub). Guarded so the tildes of a ``~~~`` code fence (which
# is stashed before this runs anyway) can never be mistaken for strikethrough.
_STRIKE_RE = re.compile(r"(?<!~)~~(?!~)([^\n]+?)(?<!~)~~(?!~)")
# ||spoiler|| (Discord/GitHub). Conservative — requires non-space inner edges so a
# logical-or like ``a || b`` (spaces around it) is never read as a spoiler.
_SPOILER_RE = re.compile(r"(?<!\|)\|\|(?!\|)(?=\S)([^\n]+?)(?<=\S)\|\|(?!\|)")
# A blockquote line AFTER escaping (``>`` became ``&gt;``), optional single space.
_QUOTE_LINE_RE = re.compile(r"^&gt;[ \t]?(.*)$")
# A run of ``> `` lines longer than this collapses to <blockquote expandable> so a
# long quote doesn't flood the chat; shorter runs stay an always-open <blockquote>.
# Set to None to never collapse (every quote stays open). See README.
EXPANDABLE_BLOCKQUOTE_MIN_LINES: int | None = 10


def _table_disp_len(s: str) -> int:
    """Visible width of an already-HTML-escaped cell (entities show as 1 char)."""
    return len(s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def _split_table_row(line: str) -> list[str]:
    """Split a `| a | b |` row into trimmed cells (outer pipes optional)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_table_pre(rows: list[list[str]]) -> str:
    """Render parsed rows (already HTML-escaped) as a column-aligned <pre> grid.

    Telegram HTML has no <table>, so a monospace block keeps the columns lined up
    — far more readable than raw `| a | b |` pipes wrapping mid-cell.
    """
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in rows) for c in range(ncol)]

    def _fmt(r: list[str]) -> str:
        return " | ".join(
            r[c] + " " * (widths[c] - _table_disp_len(r[c])) for c in range(ncol)
        )

    body = [_fmt(rows[0]), "-+-".join("-" * w for w in widths)]
    body += [_fmt(r) for r in rows[1:]]
    return "<pre>" + "\n".join(body) + "</pre>"


def _tables_to_pre(text: str, stash) -> str:
    """Replace GitHub-style markdown tables with stashed, aligned <pre> grids."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        nxt = lines[i + 1] if i + 1 < n else ""
        if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
            rows = [_split_table_row(lines[i])]
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row(lines[j]))
                j += 1
            out.append(stash(_render_table_pre(rows)))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# LaTeX -> Unicode (render-time fallback; #51)
# --------------------------------------------------------------------------- #
# Telegram can't render LaTeX. The chat system prompt asks the model to write
# plain Unicode (#43), but code mode and stray output still leak LaTeX, so we
# convert the common, UNAMBIGUOUS constructs at render time. This runs only on
# NON-code text (md_to_html stashes code first), and only rewrites LaTeX-specific
# syntax (backslash commands, ^{}/_{} scripts, math delimiters) so prose like
# "$5 and $10" or "a_b" is left untouched.
_LATEX_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "propto": "∝", "sim": "∼", "cong": "≅",
    "ll": "≪", "gg": "≫", "infty": "∞", "partial": "∂", "nabla": "∇",
    "sum": "∑", "prod": "∏", "int": "∫", "sqrt": "√", "deg": "°",
    "rightarrow": "→", "Rightarrow": "⇒", "leftarrow": "←", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "to": "→", "mapsto": "↦", "implies": "⇒", "iff": "⇔",
    "ldots": "…", "cdots": "⋯", "dots": "…", "angle": "∠",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "forall": "∀", "exists": "∃",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "µ", "nu": "ν", "xi": "ξ", "rho": "ρ",
    "pi": "π", "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
# Longest names first so e.g. \leftrightarrow wins over \leftarrow.
_LATEX_CMD_RE = re.compile(
    r"\\(" + "|".join(sorted(_LATEX_SYMBOLS, key=len, reverse=True)) + r")(?![A-Za-z])"
)
_SUP_SET = set("0123456789+-=()n")
_SUB_SET = set("0123456789+-=()")
_SUP_TAB = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB_TAB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _script(s: str, charset: set, table: dict) -> str:
    """Translate s to super/sub-script if every char is supported, else give a
    readable caret/underscore fallback so nothing is silently dropped."""
    if s and all(ch in charset for ch in s):
        return s.translate(table)
    return None  # caller decides the fallback


def _latex_to_unicode(s: str) -> str:
    if "\\" not in s and "$" not in s and "^" not in s and "_{" not in s:
        return s  # fast path: nothing LaTeX-ish present

    def _unwrap_math(m: re.Match) -> str:
        inner = m.group(1)
        # Only treat as math if it actually contains LaTeX-ish syntax — protects
        # prose like "$5 and $10" (no backslash/^/sub/brace) from being mangled.
        return inner if re.search(r"[\\^{}]|_[\d{]", inner) else m.group(0)

    s = re.sub(r"\$\$(.+?)\$\$", _unwrap_math, s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+?)\$", _unwrap_math, s)
    s = re.sub(r"\\\((.+?)\\\)", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]", r"\1", s, flags=re.DOTALL)
    # \text{..}, \mathrm{..}, \mathbf{..}, \operatorname{..} → inner text.
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\s*\{([^{}]*)\}", r"\1", s)

    def _frac(m: re.Match) -> str:
        a, b = m.group(1).strip(), m.group(2).strip()
        wa = a if len(a) <= 1 else f"({a})"
        wb = b if len(b) <= 1 else f"({b})"
        return f"{wa}/{wb}"

    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", _frac, s)
    s = re.sub(
        r"\\sqrt\s*\{([^{}]*)\}",
        lambda m: ("√(" + m.group(1) + ")") if len(m.group(1)) > 1 else "√" + m.group(1),
        s,
    )
    s = re.sub(r"\\(?:left|right|,|;|!|quad|qquad)\s?", "", s)
    s = _LATEX_CMD_RE.sub(lambda m: _LATEX_SYMBOLS[m.group(1)], s)

    def _sup(m: re.Match) -> str:
        inner = m.group(1)
        return _script(inner, _SUP_SET, _SUP_TAB) or f"^({inner})"

    def _sub(m: re.Match) -> str:
        inner = m.group(1)
        return _script(inner, _SUB_SET, _SUB_TAB) or f"_({inner})"

    s = re.sub(r"\^\{([^{}]*)\}", _sup, s)
    s = re.sub(r"\^(\w)", lambda m: _script(m.group(1), _SUP_SET, _SUP_TAB) or m.group(0), s)
    s = re.sub(r"_\{([^{}]*)\}", _sub, s)
    # Bare x_2 → subscript ONLY when preceded by an alphanumeric (so markdown
    # _italic_ — underscore followed by a letter at a word edge — is untouched).
    s = re.sub(
        r"(?<=[A-Za-z0-9])_(\d)",
        lambda m: _script(m.group(1), _SUB_SET, _SUB_TAB) or m.group(0),
        s,
    )
    return s


def _blockquotes_to_html(text: str) -> str:
    """Group runs of markdown ``> `` lines into Telegram <blockquote> blocks.

    Operates on already-escaped text (so ``>`` is ``&gt;``) AFTER code/tables are
    stashed, so a ``>`` inside code is never touched. Telegram blockquotes can't
    nest, so each run is flattened into ONE block; inline styles inside it are
    applied by the later bold/italic/strike/spoiler passes (those are allowed
    inside a blockquote). A run longer than EXPANDABLE_BLOCKQUOTE_MIN_LINES becomes
    a collapsible <blockquote expandable>.
    """
    if "&gt;" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        m = _QUOTE_LINE_RE.match(lines[i])
        if m is None:
            out.append(lines[i])
            i += 1
            continue
        inner = [m.group(1)]
        j = i + 1
        while j < n:
            mj = _QUOTE_LINE_RE.match(lines[j])
            if mj is None:
                break
            inner.append(mj.group(1))
            j += 1
        threshold = EXPANDABLE_BLOCKQUOTE_MIN_LINES
        expandable = threshold is not None and len(inner) > threshold
        tag = "<blockquote expandable>" if expandable else "<blockquote>"
        out.append(tag + "\n".join(inner) + "</blockquote>")
        i = j
    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Convert a SAFE subset of Markdown to Telegram HTML.

    Supported: fenced code blocks, inline code, **bold**/__bold__,
    *italic*/_italic_, ~~strikethrough~~, ||spoiler||, and ``> `` block quotes
    (a long run collapses to <blockquote expandable>). Everything is HTML-escaped
    first, so the output is always valid for ``parse_mode="HTML"``. If anything
    goes wrong we fall back to a fully-escaped plain string so a message is never
    lost.
    """
    if not text:
        return ""
    try:
        # 1) Escape the whole thing up front.
        escaped = escape_html(text)

        # 2) Pull out fenced code blocks first and replace them with opaque
        #    placeholders so later inline rules cannot touch their contents.
        placeholders: list[str] = []

        def _stash(html_fragment: str) -> str:
            placeholders.append(html_fragment)
            # Use a token that cannot appear after escaping or in user text and
            # will not be matched by the inline rules below.
            return f"\x00PH{len(placeholders) - 1}\x00"

        def _fence_sub(match: re.Match) -> str:
            lang = (match.group(1) or "").strip()
            body = match.group(2)
            # Strip a single trailing newline that belongs to the fence syntax.
            body = body.rstrip("\n")
            if lang:
                # Telegram renders <pre><code class="language-x"> with a language
                # label + syntax highlighting. The fence regex restricts the
                # language to a safe charset, so it needs no extra escaping.
                return _stash(
                    f'<pre><code class="language-{lang}">{body}</code></pre>'
                )
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_RE.sub(_fence_sub, escaped)
        # ~~~ fences use the same group layout, so reuse _fence_sub.
        escaped = _FENCE_TILDE_RE.sub(_fence_sub, escaped)

        # Fences without a language line / inline ``` ... ``` form.
        def _fence_nolang_sub(match: re.Match) -> str:
            body = match.group(1).strip("\n")
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_NOLANG_RE.sub(_fence_nolang_sub, escaped)

        # 3) Inline code -> <code>, also stashed so bold/italic skip it.
        def _inline_code_sub(match: re.Match) -> str:
            return _stash(f"<code>{match.group(1)}</code>")

        escaped = _INLINE_CODE_RE.sub(_inline_code_sub, escaped)

        # 3b) Markdown tables → a column-aligned <pre> grid (Telegram HTML has no
        #     <table>); stashed so the inline rules below don't touch the grid.
        escaped = _tables_to_pre(escaped, _stash)

        # 3c) ATX headers (#..######) → bold lines (Telegram has no <h*>). The
        #     whole header is bold, so redundant ** / __ inside it are dropped.
        escaped = _ATX_HEADER_RE.sub(
            lambda m: _stash("<b>" + m.group(2).replace("**", "").replace("__", "") + "</b>"),
            escaped,
        )

        # 3d) Links [text](url) → <a> (stashed so bold/italic skip the URL).
        def _link_sub(match: re.Match) -> str:
            label, url = match.group(1), match.group(2)
            if not re.match(r"(?:https?:|tg:|mailto:)", url):
                return match.group(0)  # not a real URL — leave the text literal
            return _stash(f'<a href="{url}">{label}</a>')

        escaped = _LINK_RE.sub(_link_sub, escaped)

        # 3d2) Block quotes: group ``> `` line runs into <blockquote> (long runs
        #     collapse to <blockquote expandable>). Done after code/tables are
        #     stashed (so quotes inside code are untouched) and before the inline
        #     passes (which then style the quote's contents — allowed inside it).
        escaped = _blockquotes_to_html(escaped)

        # 3e) LaTeX → Unicode on the remaining (non-code) text (#51). Code spans
        #     are already stashed as placeholders, so they are never touched.
        escaped = _latex_to_unicode(escaped)

        # 4) Inline styles. Bold first so ** is consumed before * italic; then
        #    ~~strike~~ and ||spoiler||; italic last (its single * / _ is the most
        #    fragile). All of these may nest and may sit inside a <blockquote>.
        escaped = _BOLD_STAR_RE.sub(r"<b>\1</b>", escaped)
        escaped = _BOLD_USCORE_RE.sub(r"<b>\1</b>", escaped)
        escaped = _STRIKE_RE.sub(r"<s>\1</s>", escaped)
        escaped = _SPOILER_RE.sub(r"<tg-spoiler>\1</tg-spoiler>", escaped)
        escaped = _ITALIC_STAR_RE.sub(r"<i>\1</i>", escaped)
        escaped = _ITALIC_USCORE_RE.sub(r"<i>\1</i>", escaped)

        # 5) Restore stashed fragments. Loop because a stashed fragment (header /
        #    table / link) can itself contain another placeholder; bound the
        #    passes (and the index) so a stray token can never spin or crash.
        def _restore(match: re.Match) -> str:
            idx = int(match.group(1))
            return placeholders[idx] if 0 <= idx < len(placeholders) else match.group(0)

        for _ in range(len(placeholders) + 1):
            if "\x00PH" not in escaped:
                break
            escaped = _PH_RE.sub(_restore, escaped)
        return escaped
    except Exception:
        # Never let formatting crash a send; fall back to plain escaped text.
        return escape_html(text)


# An empty rendered code box: <pre></pre> or <pre><code class="language-x">
# </code></pre> with no inner text. When split_message hard-cuts a single very
# long line inside a fence (minified JS, base64, a data URI), a lone fence can
# render to one of these — a blank tap-to-copy box that should never be sent.
_EMPTY_RENDER_RE = re.compile(
    r"\A<pre>(?:<code(?:\s[^>]*)?>\s*</code>)?</pre>\Z"
)


def is_empty_render(html: str) -> bool:
    """True when *html* is an empty code box with no inner text.

    Matches ``<pre></pre>`` and ``<pre><code class="language-x"></code></pre>``
    (any ``<code>`` attributes) after stripping surrounding whitespace. Such
    chunks come from hard-cutting a single over-long line inside a fence; they
    render as a blank tap-to-copy box and must be skipped before sending.
    """
    if not html:
        return False
    return _EMPTY_RENDER_RE.match(html.strip()) is not None


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #
def split_message(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split *text* into chunks no longer than *limit* characters.

    Prefers paragraph (blank-line) and then line boundaries so we never cut in
    the middle of a line when it can be avoided. A single line longer than the
    limit is hard-cut. Never returns an empty list (returns ``[""]`` for empty
    input so the caller can simply skip empty chunks).
    """
    if limit <= 0:
        limit = SAFE_LIMIT
    if text is None or text == "":
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    def _flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    # Split into lines, preserving structure. Each "piece" carries the newline
    # that split() removed (for every line after the first) so concatenating all
    # chunks reproduces the original text exactly.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        piece = line if i == 0 else "\n" + line

        # A single line (with its leading newline) longer than the limit must be
        # hard-cut. The first hard-cut segment keeps the leading newline so the
        # round-trip is preserved.
        if len(piece) > limit:
            _flush()
            for start in range(0, len(piece), limit):
                chunks.append(piece[start : start + limit])
            continue

        if len(current) + len(piece) <= limit:
            current += piece
        else:
            # The current chunk is full. Carry this piece (newline included) to
            # the next chunk so the separating newline is not lost.
            _flush()
            current = piece

    _flush()
    if not chunks:
        return [""]
    return chunks


_FENCE_LINE_RE = re.compile(r"^[ \t]*```([A-Za-z0-9_+\-.#]*)[ \t]*$")


def split_markdown(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split raw Markdown into chunks, repairing fenced code blocks that
    straddle a chunk boundary.

    Splitting raw text (then rendering each chunk independently) is required so
    md_to_html never sees a tag cut in half. But a plain raw split can leave an
    incomplete ``` fence in each half, so neither renders as <pre> and the user
    sees literal backticks. Here we close any open fence at the end of a chunk
    and reopen it (with the same language hint) at the start of the next, so
    every chunk contains complete, independently-renderable fences.
    """
    # Reserve a little headroom for the fence markers we may add per chunk
    # (a reopened ```lang line plus a closing ``` line) so a repaired chunk
    # still stays within `limit`.
    inner_limit = max(1, limit - 24)
    chunks = split_message(text, limit=inner_limit)
    if len(chunks) <= 1:
        return chunks

    repaired: list[str] = []
    open_lang: str | None = None  # language of a fence carried over, if any
    for chunk in chunks:
        prefix = ""
        if open_lang is not None:
            # Reopen the fence carried from the previous chunk.
            prefix = f"```{open_lang}\n"

        # Walk the chunk's lines to track fence open/close state. Start from the
        # carried-over state so a fence opened in a prior chunk counts as open.
        in_fence = open_lang is not None
        lang_here = open_lang
        for line in chunk.split("\n"):
            m = _FENCE_LINE_RE.match(line)
            if m:
                if in_fence:
                    in_fence = False
                    lang_here = None
                else:
                    in_fence = True
                    lang_here = m.group(1) or ""

        body = prefix + chunk
        if in_fence:
            # This chunk ends inside a fence: close it now and remember the
            # language so the next chunk reopens it.
            if not body.endswith("\n"):
                body += "\n"
            body += "```"
            open_lang = lang_here or ""
        else:
            open_lang = None
        repaired.append(body)

    return repaired


def render_within_limit(raw: str, hard_limit: int = HARD_LIMIT) -> list[str]:
    """Render one raw-Markdown chunk to HTML, guaranteeing each result fits
    Telegram's hard per-message limit.

    split_markdown sizes chunks by RAW character count, but md_to_html escapes
    ``&``/``<``/``>`` (up to ~5x) and adds tags, so an entity-dense raw chunk can
    render past 4096 — Telegram then rejects the send and it is silently dropped.
    Here we render, and when the HTML overflows we re-split the RAW source smaller
    and re-render (never splitting rendered HTML, which would cut a tag), with a
    hard-cut floor so a pathological single long line still terminates.
    """
    html = md_to_html(raw) or "…"
    if len(html) <= hard_limit:
        return [html]
    # Re-split the raw source on boundaries with a shrinking budget.
    raw_limit = max(256, len(raw) // 2)
    while raw_limit >= 256:
        pieces = split_markdown(raw, limit=raw_limit)
        if len(pieces) > 1:
            rendered = [md_to_html(p) or "…" for p in pieces]
            if all(len(h) <= hard_limit for h in rendered):
                return rendered
        raw_limit //= 2
    # Last resort: hard-cut the RAW text. md_to_html escapes first, so even a cut
    # mid-fence yields valid (escaped) HTML, never a broken tag. ``&`` expands to
    # 5 chars; a raw step of hard_limit//6 keeps each rendered piece in bounds.
    step = max(256, hard_limit // 6)
    out: list[str] = []
    for i in range(0, len(raw), step):
        out.append(md_to_html(raw[i : i + step]) or "…")
    return out or ["…"]


# A complete fenced code block (``` or ~~~), language optional, on raw text.
_FENCE_BLOCK_RE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?```"
    r"|~~~[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?~~~",
    re.DOTALL,
)


def segment_blocks(text: str) -> list[str]:
    """Split raw model text into ordered segments, ISOLATING each fenced code
    block into its own segment.

    Sending each code block as its own message makes it trivially copyable
    (long-press the message → Copy grabs the whole snippet) on every Telegram
    client — including those that don't show a per-block copy button and only
    copy the tapped token. Prose between/around blocks forms its own segments.
    Returns [] for empty input; a single segment when there are no code blocks.
    """
    if not text or not text.strip():
        return []
    segments: list[str] = []
    last = 0
    for m in _FENCE_BLOCK_RE.finditer(text):
        pre = text[last : m.start()].strip()
        if pre:
            segments.append(pre)
        segments.append(m.group(0).strip())
        last = m.end()
    tail = text[last:].strip()
    if tail:
        segments.append(tail)
    return segments or [text.strip()]


def split_closed_blocks(text: str) -> tuple[str, str]:
    """Split streaming text at the end of the last FULLY-CLOSED fenced block.

    Returns ``(prefix, remainder)``: *prefix* is everything up to and including
    the last fenced code block that is both closed AND followed by a newline
    (proof the model has moved past it, so it will not grow further); *remainder*
    is the still-streaming tail. Returns ``("", text)`` when no such block exists.

    Used for LIVE code-block splitting while streaming (#93): the prefix is
    committed as its own message(s) — prose split off, the code block isolated
    into a copyable message — and the remainder keeps streaming in the draft, so
    a finished snippet becomes copyable immediately and the live draft stays
    smooth (it no longer carries a completed block whose closing tag would snap
    the animation).
    """
    if not text:
        return "", text
    end = 0
    for m in _FENCE_BLOCK_RE.finditer(text):
        after = m.end()
        # Only flush a block the model has definitively finished: require a
        # newline right after the closing fence. A block whose closing fence is
        # the last thing on screen might still grow (more backticks); finish()
        # commits such a trailing block at turn end anyway.
        if text.startswith("\n", after):
            end = after + 1
        elif text.startswith("\r\n", after):
            end = after + 2
    if end == 0:
        return "", text
    return text[:end], text[end:]


def should_send_as_file(text: str) -> bool:
    """True for very long output the caller may prefer to send as a document."""
    return bool(text) and len(text) > FILE_THRESHOLD


def as_document(text: str, filename: str) -> BufferedInputFile:
    """Wrap *text* as an in-memory file aiogram can upload.

    Text documents get a UTF-8 BOM so clients that would otherwise guess a legacy
    charset (rendering Cyrillic/other non-ASCII as mojibake) detect UTF-8.
    """
    bom = chr(0xFEFF)  # UTF-8 BOM, written explicitly (it is invisible in source)
    data = text or ""
    if filename.endswith((".md", ".txt")) and not data.startswith(bom):
        data = bom + data
    return BufferedInputFile(data.encode("utf-8"), filename=filename)
