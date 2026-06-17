"""Telegram Bot API 10.1 ``sendRichMessage`` binding (#164 — native tables).

Bot API 10.1 (2026-06-11) added ``sendRichMessage``, which renders rich content
(tables, headings, nested lists, …) that the classic ``parse_mode=HTML`` path
cannot. aiogram 3.28 ships no binding for it yet, so we declare the method by
hand — a ``TelegramMethod`` is just a pydantic model with ``__api_method__`` /
``__returning__``, routed through the bot's own (proxy-aware) session.

We always pass the ``rich_message`` as an ``InputRichMessage`` in its ``{"html":
…}`` form — the docs require exactly one of ``html`` / ``markdown``. The HTML may
contain ``<table bordered striped>…</table>`` with ``<th>``/``<td>``, ``align``,
``colspan``/``rowspan`` and ``<caption>`` (see markup.table_to_rich_html).
"""

from __future__ import annotations

from typing import Any

from aiogram.methods.base import TelegramMethod
from aiogram.types import Message


class SendRichMessage(TelegramMethod[Message]):
    """Send a rich message (Bot API 10.1). On success the sent Message is returned.

    Only the fields we use are declared; all are optional except ``chat_id`` and
    ``rich_message``. ``rich_message`` is an InputRichMessage dict, e.g.
    ``{"html": "<table>…</table>"}`` or ``{"markdown": "# …"}``. ``reply_markup``
    is supported (an inline keyboard), so menu screens can be rich too (#172).
    """

    __returning__ = Message
    __api_method__ = "sendRichMessage"

    chat_id: int | str
    rich_message: dict[str, Any]
    message_thread_id: int | None = None
    disable_notification: bool | None = None
    protect_content: bool | None = None
    reply_markup: Any | None = None


class SendRichMessageDraft(TelegramMethod[bool]):
    """Stream a PARTIAL rich message while generating (#172, Bot API 10.1). The draft
    is ephemeral (~30s preview); updates that reuse the same ``draft_id`` are animated
    by the client — so the reply streams ALREADY FORMATTED. Persist the final text with
    a normal ``sendRichMessage`` once done. Private chats only. Returns True."""

    __returning__ = bool
    __api_method__ = "sendRichMessageDraft"

    chat_id: int
    draft_id: int
    rich_message: dict[str, Any]
    message_thread_id: int | None = None
