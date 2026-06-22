"""Allowlist-based access control middleware for aiogram.

Drops every incoming update whose originating user is not permitted by the
configured allowlist. Works for both ``Message`` and ``CallbackQuery`` events
(and anything else exposing ``from_user``), and fails closed (drops) for any
update type without an identifiable user.
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
from app.telegram import markup

# #328: maintenance freeze. While the sentinel file exists, the bot replies a "back soon" stub
# to every allowed user and DROPS the update (no handler runs → no new session/turn data is
# created), so the dataset stays stable for a migration. Toggled LIVE (no restart) via
# `touch`/`rm` of the file; checked per-update (a cheap stat).
_MAINTENANCE_SENTINEL = os.environ.get("MAINTENANCE_FILE", "MAINTENANCE")


def maintenance_active() -> bool:
    try:
        return os.path.exists(_MAINTENANCE_SENTINEL)
    except OSError:
        return False


class AllowlistMiddleware(BaseMiddleware):
    """Reject any update that is not permitted by the allowlist.

    Registered as an outer middleware on both ``dp.message`` and
    ``dp.callback_query``. If the event's user is not allowed, the handler
    chain is short-circuited (returns ``None``) so no downstream handler ever
    sees the update.
    """

    def __init__(self, allowlist: Any, owner_id: Optional[int] = None,
                 notify_owner: bool = True) -> None:
        super().__init__()
        self.allowlist = allowlist
        # #277: so the owner can add someone whose numeric id they don't have (only a
        # phone number / a name), an UNKNOWN user's first attempt notifies the owner with
        # the id + name + one-tap Allow buttons. Throttled per-user so it can't be spammed.
        self.owner_id = owner_id
        self.notify_owner = notify_owner
        self._notified: dict[int, float] = {}
        self._notify_window = 6 * 3600  # at most one owner ping per user per 6h

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
            with contextlib.suppress(Exception):
                await self._maybe_notify_owner(event, uid, uname)
            return None
        # #328: maintenance freeze — reply a stub and DROP the update (no handler → no new
        # session/turn data), keeping the dataset stable for a migration.
        if maintenance_active():
            with contextlib.suppress(Exception):
                await self._reply_maintenance(event, uid)
            return None
        # Best-effort pin of the latest known username for this user.
        try:
            self.allowlist.pin(uid, uname)
        except Exception:
            pass
        return await handler(event, data)

    async def _reply_maintenance(self, event: TelegramObject, uid: Optional[int]) -> None:
        """#328: tell an allowed user the bot is briefly down for maintenance. A CallbackQuery
        (button tap) gets a toast; a Message gets a reply."""
        lang = i18n.cached_lang(uid) if uid is not None else i18n.DEFAULT_LANG
        text = i18n.t("maintenance.notice", lang)
        if getattr(event, "data", None) is not None:      # CallbackQuery → toast
            await event.answer(text, show_alert=True)
        else:                                             # Message → reply
            await event.answer(text)

    async def _maybe_notify_owner(self, event: TelegramObject, uid: Optional[int],
                                  uname: Optional[str]) -> None:
        """#277: ping the owner that an UNKNOWN user tried to use the bot, with the user's
        numeric id + name and one-tap Allow buttons — the way to grant access to someone
        whose id you don't know (you only have their phone/name): they tap the bot, you
        allow from the notice. Only for real Message attempts; throttled per user."""
        # Only for a real text message attempt (a /start or any typed line) — not
        # callbacks/service updates. Duck-typed (`.text`) so it's unit-testable.
        if (not self.notify_owner or self.owner_id is None or uid is None
                or uid == self.owner_id or not getattr(event, "text", None)):
            return
        now = time.monotonic()
        last = self._notified.get(uid)
        if last is not None and (now - last) < self._notify_window:
            return
        # #290: prune stale entries so _notified can't grow unbounded on a flood of distinct
        # unknown ids — anything older than the throttle window is safe to forget (its next
        # attempt would re-notify anyway).
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
            # #277: silent — an access request shouldn't buzz the owner's phone.
            await bot.send_message(self.owner_id, text, reply_markup=kb,
                                   parse_mode="HTML", disable_notification=True)


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
