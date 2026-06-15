"""Allowlist-based access control middleware for aiogram.

Drops every incoming update whose originating user is not permitted by the
configured allowlist. Works for both ``Message`` and ``CallbackQuery`` events
(and anything else exposing ``from_user``), and fails closed (drops) for any
update type without an identifiable user.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

import db
import i18n


class AllowlistMiddleware(BaseMiddleware):
    """Reject any update that is not permitted by the allowlist.

    Registered as an outer middleware on both ``dp.message`` and
    ``dp.callback_query``. If the event's user is not allowed, the handler
    chain is short-circuited (returns ``None``) so no downstream handler ever
    sees the update.
    """

    def __init__(self, allowlist: Any) -> None:
        super().__init__()
        self.allowlist = allowlist

    @staticmethod
    def _extract(event: TelegramObject) -> tuple[Optional[int], Optional[str]]:
        """Best-effort extraction of the acting user's id and username.

        Returns ``(None, None)`` when the event has no associated user (e.g.
        service messages, channel posts, or update types we do not handle).
        """
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return None, None
        return getattr(from_user, "id", None), getattr(from_user, "username", None)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        uid, uname = self._extract(event)
        if uid is None or not self.allowlist.is_allowed(uid, uname):
            # Drop the update: do not invoke the downstream handler.
            return None
        # Best-effort pin of the latest known username for this user.
        try:
            self.allowlist.pin(uid, uname)
        except Exception:
            pass
        return await handler(event, data)


class LanguageMiddleware(BaseMiddleware):
    """Resolve and cache each allowed user's interface locale.

    Registered as an outer middleware (after the allowlist) on both ``dp.message``
    and ``dp.callback_query``. On a user's first update this process, it reads any
    explicit choice from the DB; with none, it auto-detects from the Telegram
    client ``language_code`` (ru -> Russian, anything else -> English) without
    persisting — so the locale tracks the client until the user picks one via
    /language. The resolved value is cached in ``i18n`` so the hot path never hits
    the DB, and exposed to handlers as ``data["lang"]``.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        uid = getattr(from_user, "id", None)
        if uid is not None:
            if not i18n.has_lang(uid):
                stored = None
                try:
                    stored = await db.get_user_lang(uid)
                except Exception:
                    stored = None
                if stored:
                    lang = i18n.normalize_lang(stored)
                else:
                    lang = i18n.normalize_lang(
                        getattr(from_user, "language_code", None)
                    )
                i18n.remember_lang(uid, lang)
            data["lang"] = i18n.cached_lang(uid)
        return await handler(event, data)
