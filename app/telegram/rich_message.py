"""Binding for Telegram's ``sendRichMessage`` Bot API method.

- aiogram ships no binding; declared by hand
- ``rich_message`` is always sent in ``html`` form
- HTML may contain tables with spans and captions
"""

from __future__ import annotations

from typing import Any, Union

from aiogram.methods.base import TelegramMethod
from aiogram.types import Message


class SendRichMessage(TelegramMethod[Message]):
    """Send a rich message; returns the sent Message.

    - ``rich_message`` is an ``InputRichMessage`` dict (``html`` or ``markdown``)
    - ``reply_markup`` supports an inline keyboard
    """

    __returning__ = Message
    __api_method__ = "sendRichMessage"

    chat_id: int | str
    rich_message: dict[str, Any]
    message_thread_id: int | None = None
    disable_notification: bool | None = None
    protect_content: bool | None = None
    reply_markup: Any | None = None


class EditRichMessage(TelegramMethod[Union[Message, bool]]):
    """Edit a message in place into a rich message.

    - Menus render with the same rich font as replies
    - ``rich_message`` is an ``InputRichMessage`` dict, here ``html``
    - ``reply_markup`` re-attaches the inline keyboard
    - Returns edited Message, or ``True`` for inline
    """

    __returning__ = Union[Message, bool]
    __api_method__ = "editMessageText"

    chat_id: int | str | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    rich_message: dict[str, Any]
    reply_markup: Any | None = None


class SendRichMessageDraft(TelegramMethod[bool]):
    """Stream a partial rich message draft while generating.

    - Draft is ephemeral, about 30 seconds of preview
    - Updates reusing the same ``draft_id`` are animated
    - Persist final text via ``sendRichMessage``; private chats only
    """

    __returning__ = bool
    __api_method__ = "sendRichMessageDraft"

    chat_id: int
    draft_id: int
    rich_message: dict[str, Any]
    message_thread_id: int | None = None
    # Client stop button on a draft sends a stop update.
    # - Also controls whether the draft stays on screen
    can_stop: bool | None = None
    keep_on_stop: bool | None = None


def stopped_generation_of(update) -> tuple[int, int] | None:
    """Return the stopped-generation update's ``(chat_id, draft_id)``, else None.

    - Read from raw fields aiogram keeps for unknown updates
    """
    extra = getattr(update, "model_extra", None) or {}
    raw = extra.get("stopped_message_generation")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["chat"]["id"]), int(raw["draft_id"])
    except (KeyError, TypeError, ValueError):
        return None
