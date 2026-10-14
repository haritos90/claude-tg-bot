"""Allowlist access-control middleware for aiogram.

- Drops updates from users the allowlist denies
- Fails closed when no user is identifiable
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           TelegramObject)

from app.storage import db
from app import i18n
from app import REPO_ROOT
from app.telegram import markup

# Maintenance freeze: sentinel file makes the bot reply a stub.
# - Updates are dropped while the file exists
# - Toggled live with `touch`/`rm`, checked per update
# - Absolute path under repo root, independent of cwd
# - Override with `MAINTENANCE_FILE`
_MAINTENANCE_SENTINEL = os.environ.get("MAINTENANCE_FILE") or str(REPO_ROOT / "MAINTENANCE")


def maintenance_active() -> bool:
    try:
        return os.path.exists(_MAINTENANCE_SENTINEL)
    except OSError:
        return False


class AllowlistMiddleware(BaseMiddleware):
    """Drop updates from users the allowlist denies.

    - Outer middleware on messages and callback queries
    - Short-circuits so no handler sees the update
    """

    def __init__(self, allowlist: Any, owner_id: Optional[int] = None,
                 notify_owner: bool = True) -> None:
        super().__init__()
        self.allowlist = allowlist
        # An unknown user's first attempt notifies the owner.
        # - Throttled per user to prevent spam
        self.owner_id = owner_id
        self.notify_owner = notify_owner
        self._notified: dict[int, float] = {}
        self._notify_window = 6 * 3600  # At most one ping per 6h

    @staticmethod
    def _extract(event: TelegramObject) -> tuple[Optional[int], Optional[str]]:
        """Best-effort extraction of the acting user's id and username.

        - Returns `(None, None)` when the event has no user
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
            # Drop the update; skip downstream handlers.
            with contextlib.suppress(Exception):
                await self._maybe_notify_owner(event, uid, uname)
            return None
        # Maintenance freeze: reply with a stub, drop update.
        if maintenance_active():
            with contextlib.suppress(Exception):
                await self._reply_maintenance(event, uid)
            return None
        # Best-effort pin of the user's latest username.
        try:
            self.allowlist.pin(uid, uname)
        except Exception:
            pass
        return await handler(event, data)

    async def _reply_maintenance(self, event: TelegramObject, uid: Optional[int]) -> None:
        """Tell an allowed user the bot is under maintenance.

        - Callback queries get a toast; messages get a reply
        """
        lang = i18n.cached_lang(uid) if uid is not None else i18n.DEFAULT_LANG
        text = i18n.t("maintenance.notice", lang)
        if getattr(event, "data", None) is not None:      # Callback query gets a toast
            await event.answer(text, show_alert=True)
        else:                                             # Message gets a reply
            await event.answer(text)

    async def _maybe_notify_owner(self, event: TelegramObject, uid: Optional[int],
                                  uname: Optional[str]) -> None:
        """Notify the owner that an unknown user tried the bot.

        - Includes id, name, and one-tap Allow buttons
        - Only for text messages; throttled per user
        """
        # Only text message attempts, not callbacks.
        # - Duck-typed on `.text` for unit tests
        if (not self.notify_owner or self.owner_id is None or uid is None
                or uid == self.owner_id or not getattr(event, "text", None)):
            return
        now = time.monotonic()
        last = self._notified.get(uid)
        if last is not None and (now - last) < self._notify_window:
            return
        # Prune stale entries so `_notified` stays bounded.
        if len(self._notified) > 256:
            cutoff = now - self._notify_window
            for k in [k for k, t in self._notified.items() if t < cutoff]:
                del self._notified[k]
        self._notified[uid] = now
        bot = getattr(event, "bot", None)
        if bot is None:
            return
        lang = i18n.cached_lang(self.owner_id)
        fu = getattr(event, "from_user", None)
        full = " ".join(p for p in (getattr(fu, "first_name", None),
                                    getattr(fu, "last_name", None)) if p) or "—"
        who = markup.escape_html(full)
        if uname:
            who += f" @{markup.escape_html(uname)}"
        text = i18n.t("access.request_owner", lang, who=who, id=uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.t("access.req_allow_chat", lang),
                                 callback_data=f"req:al:{uid}"),
            InlineKeyboardButton(text=i18n.t("access.req_allow_code", lang),
                                 callback_data=f"req:ac:{uid}"),
        ]])
        with contextlib.suppress(Exception):
            # Silent, so access requests don't buzz the owner.
            await bot.send_message(self.owner_id, text, reply_markup=kb,
                                   parse_mode="HTML", disable_notification=True)


class LanguageMiddleware(BaseMiddleware):
    """Resolve and cache each allowed user's interface locale.

    - An explicit DB choice wins
    - Otherwise auto-detect from client `language_code`, unpersisted
    - Exposed to handlers as `data["lang"]`
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
