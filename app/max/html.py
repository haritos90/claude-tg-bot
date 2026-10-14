"""Convert Telegram HTML and keyboards to MAX format.

- Drops what MAX lacks, e.g. `tg-spoiler`, `tg-emoji`
- MAX text limit is 4000 chars; long chunks re-split
"""

from __future__ import annotations

import html as _html
import re
from typing import Any

from app.max.client import BUTTON_TEXT_LIMIT, CALLBACK_PAYLOAD_LIMIT, TEXT_LIMIT
from app.telegram import markup

SAFE_LIMIT = TEXT_LIMIT - 100   # headroom: limit may count rendered chars

_PRE_CODE_OPEN = re.compile(r"<pre>\s*<code(?:\s+class=\"[^\"]*\")?>", re.I)
_PRE_CODE_CLOSE = re.compile(r"</code>\s*</pre>", re.I)
_DROP_WRAPPERS = re.compile(
    r"</?(?:tg-spoiler|tg-emoji|span)(?:\s+[^>]*)?>", re.I)
_BLOCKQUOTE_ATTRS = re.compile(r"<blockquote\s+[^>]*>", re.I)
_UNKNOWN_TAG = re.compile(
    r"</?(?!b\b|strong\b|i\b|em\b|u\b|ins\b|s\b|del\b|strike\b|code\b|pre\b|a\b|blockquote\b"
    r"|h[1-4]\b|mark\b)[a-zA-Z][a-zA-Z0-9-]*(?:\s+[^>]*)?>")
_ANY_TAG = re.compile(r"<[^>]+>")
_STRIKE = re.compile(r"<(/?)strike>", re.I)


def tg_html_to_max(text: str) -> str:
    """Translate the bot's Telegram HTML subset into MAX-renderable HTML."""
    if not text:
        return ""
    out = _PRE_CODE_OPEN.sub("<pre>", text)
    out = _PRE_CODE_CLOSE.sub("</pre>", out)
    out = _DROP_WRAPPERS.sub("", out)
    out = _BLOCKQUOTE_ATTRS.sub("<blockquote>", out)
    out = _STRIKE.sub(r"<\1s>", out)
    out = _UNKNOWN_TAG.sub("", out)
    return out


def strip_tags(text: str) -> str:
    """Plain text of an HTML fragment.

    - Fallback when the platform rejects markup
    """
    return _html.unescape(_ANY_TAG.sub("", text or ""))


def split_html(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Chunks that each fit a MAX message.

    - Only chunks between the two limits are re-split
    """
    if len(text) <= limit:
        return [text]
    return [c for c in markup.split_message(text, limit) if c.strip()] or [text[:limit]]


def keyboard_to_max(reply_markup: Any) -> dict | None:
    """Convert an aiogram inline keyboard to a MAX `inline_keyboard` attachment.

    - Callback buttons map 1:1; URL buttons become `link`
    - Anything else returns None
    """
    if reply_markup is None:
        return None
    rows = getattr(reply_markup, "inline_keyboard", None)
    if rows is None and isinstance(reply_markup, dict):
        rows = reply_markup.get("inline_keyboard")
    if not rows:
        return None
    buttons: list[list[dict]] = []
    for row in rows:
        out_row: list[dict] = []
        for btn in row:
            text = getattr(btn, "text", None) if not isinstance(btn, dict) else btn.get("text")
            data = getattr(btn, "callback_data", None) if not isinstance(btn, dict) else btn.get("callback_data")
            url = getattr(btn, "url", None) if not isinstance(btn, dict) else btn.get("url")
            text = (text or " ")[:BUTTON_TEXT_LIMIT]
            if data is not None:
                out_row.append({"type": "callback", "text": text,
                                "payload": str(data)[:CALLBACK_PAYLOAD_LIMIT]})
            elif url:
                out_row.append({"type": "link", "text": text, "url": url})
        if out_row:
            buttons.append(out_row[:7])
    if not buttons:
        return None
    return {"type": "inline_keyboard", "payload": {"buttons": buttons[:30]}}
