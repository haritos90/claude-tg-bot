"""aiogram sessions that carry MAX traffic.

- `MaxSession` translates Bot API methods into MAX API calls
- `RoutingSession` routes by chat, callback, or file id
- Addressless calls (`getMe`, `getUpdates`) stay on Telegram
- No streaming: the first draft posts a "Thinking…" placeholder
- Unsupported methods raise `TelegramBadRequest`
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import time
from typing import Any

from aiogram.client.default import Default
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import File, Message, User
from aiogram.types.input_file import InputFile

from app.max import html as mhtml
from app.max.client import COMMANDS_LIMIT, MaxApi, MaxApiError
from app.max.ids import FileRegistry, MidRegistry, is_internal_max, to_internal, to_max
from app.telegram import markup

logger = logging.getLogger(__name__)

PLACEHOLDER_TTL = 15 * 60   # stale placeholder is dropped, not reused
_THINKING_PREFIX = "💭 "


class MaxSession(BaseSession):
    """The MAX translator, one per bot token."""

    def __init__(self, api: MaxApi) -> None:
        super().__init__()
        self.api = api
        self.mids = MidRegistry()
        self.files = FileRegistry()
        # Internal user id to MAX dialog chat_id, for chat actions.
        self.chat_of_user: dict[int, int] = {}
        # Internal chat id to (live placeholder mid, monotonic timestamp).
        self._placeholders: dict[int, tuple[str, float]] = {}
        # mid to last body sent, for keyboard-only edits.
        self._bodies: dict[str, dict] = {}
        self.bot_user: dict | None = None
        self._unsupported: set[str] = set()
        self._handlers = {
            "sendMessage": self._send_message,
            "sendRichMessage": self._send_rich,
            "sendMessageDraft": self._draft,
            "sendRichMessageDraft": self._draft,
            "editMessageText": self._edit_text,
            "editMessageReplyMarkup": self._edit_markup,
            "deleteMessage": self._delete,
            "answerCallbackQuery": self._answer_callback,
            "sendPhoto": self._send_photo,
            "sendDocument": self._send_document,
            "sendLocation": self._send_location,
            "sendVenue": self._send_location,
            "sendChatAction": self._chat_action,
            "setMyCommands": self._set_commands,
            "getMe": self._get_me,
            "getFile": self._get_file,
        }

    # ---- BaseSession ----
    async def close(self) -> None:
        await self.api.close()

    @staticmethod
    def embeds_rich_media(chat_id) -> bool:
        """MAX has no rich blocks: pins and pictures interleave."""
        return False

    async def make_request(self, bot, method, timeout=None):
        name = method.__api_method__
        handler = self._handlers.get(name)
        if handler is None:
            if name not in self._unsupported:
                self._unsupported.add(name)
                logger.info("MAX: Bot API method %s has no MAX equivalent; refused", name)
            raise TelegramBadRequest(method=method, message=f"MAX: unsupported method {name}")
        try:
            return await handler(bot, method)
        except MaxApiError as exc:
            raise TelegramBadRequest(method=method, message=f"MAX: {exc}") from exc

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536,
                             raise_for_status=True):
        rf = self.files.by_path(url)
        if rf is None:
            raise RuntimeError(f"MAX: unknown file path {url!r}")
        async for chunk in self.api.download(rf.url, chunk_size=chunk_size):
            yield chunk

    # ---- helpers ----
    @staticmethod
    def _parse_mode(bot, method) -> str | None:
        pm = getattr(method, "parse_mode", None)
        if isinstance(pm, Default):
            pm = bot.default.parse_mode
        return pm

    def _html_of(self, bot, method, text: str | None) -> str:
        """The message text as MAX HTML, whatever the parse mode."""
        if not text:
            return ""
        pm = (self._parse_mode(bot, method) or "").lower()
        if pm == "html":
            return mhtml.tg_html_to_max(text)
        if pm.startswith("markdown"):
            return mhtml.tg_html_to_max(markup.md_to_html(text))
        return markup.escape_html(text)

    @staticmethod
    def _link_preview_disabled(method) -> bool | None:
        lp = getattr(method, "link_preview_options", None)
        if isinstance(lp, Default) or lp is None:
            return None
        return True if getattr(lp, "is_disabled", None) else None

    def _message(self, bot, chat_id: int, mid: str, text: str, kb: dict | None = None) -> Message:
        """A synthetic aiogram `Message` for a just-sent message."""
        me = self.bot_user or {}
        data = {
            "message_id": self.mids.int_of(mid),
            "date": int(time.time()),
            "chat": {"id": int(chat_id), "type": "private"},
            "from": {"id": to_internal(me.get("user_id", 0)), "is_bot": True,
                     "first_name": me.get("first_name") or "bot",
                     "username": me.get("username")},
            "text": text or None,
        }
        return Message.model_validate(data, context={"bot": bot})

    async def _post(self, chat_id: int, body: dict, *, notify: bool = True,
                    link_preview_disabled: bool | None = None) -> str:
        """`POST /messages` to a MAX user, returning the new mid.

        - HTML the platform rejects is re-sent as plain text
        """
        if not notify:
            body = {**body, "notify": False}
        try:
            msg = await self.api.send_message(user_id=to_max(chat_id), body=body,
                                              disable_link_preview=link_preview_disabled)
        except MaxApiError as exc:
            if exc.status != 400 or body.get("format") != "html":
                raise
            logger.warning("MAX: html rejected (%s); re-sending as plain text", exc.code)
            plain = {**body, "text": mhtml.strip_tags(body.get("text") or ""), "format": None}
            msg = await self.api.send_message(user_id=to_max(chat_id), body=plain,
                                              disable_link_preview=link_preview_disabled)
        mid = ((msg or {}).get("body") or {}).get("mid") or f"sent:{time.time_ns()}"
        self._bodies[mid] = body
        return mid

    async def _edit(self, mid: str, body: dict) -> None:
        try:
            await self.api.edit_message(mid, body)
        except MaxApiError as exc:
            if exc.status != 400 or body.get("format") != "html":
                raise
            logger.warning("MAX: html rejected on edit (%s); plain text instead", exc.code)
            await self.api.edit_message(mid, {**body, "text": mhtml.strip_tags(body.get("text") or ""),
                                              "format": None})
        self._bodies[mid] = body

    def _take_placeholder(self, chat_id: int) -> str | None:
        entry = self._placeholders.pop(int(chat_id), None)
        if entry is None:
            return None
        mid, ts = entry
        if time.monotonic() - ts > PLACEHOLDER_TTL:
            asyncio.ensure_future(self._delete_quiet(mid))
            return None
        return mid

    async def _delete_quiet(self, mid: str) -> None:
        with contextlib.suppress(Exception):
            await self.api.delete_message(mid)
        self._bodies.pop(mid, None)

    async def _deliver(self, bot, chat_id: int, html: str, kb: dict | None = None, *,
                       notify: bool = True, link_preview_disabled: bool | None = None,
                       media: list[dict] | None = None) -> Message:
        """Send text split to 4000 chars, plus media and keyboard.

        - A live placeholder becomes the first part
        - Media can't edit in place; placeholder removed
        """
        chat_id = int(chat_id)
        chunks = mhtml.split_html(html) if html else [""]
        ph = self._take_placeholder(chat_id)
        if ph and media:
            await self._delete_quiet(ph)
            ph = None
        mid = ""
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            body: dict[str, Any] = {"text": chunk or None, "format": "html" if chunk else None}
            atts: list[dict] = []
            if media and i == 0:
                atts.extend(media)
            if kb and last:
                atts.append(kb)
            if atts:
                body["attachments"] = atts
            if ph and i == 0:
                await self._edit(ph, body)
                mid = ph
            else:
                mid = await self._post(chat_id, body, notify=notify and last,
                                       link_preview_disabled=link_preview_disabled)
        return self._message(bot, chat_id, mid, mhtml.strip_tags(chunks[-1]), kb)

    @staticmethod
    async def _bytes_of(bot, obj) -> tuple[bytes, str]:
        """(data, filename) of an aiogram `InputFile`."""
        name = getattr(obj, "filename", None) or "file.bin"
        if hasattr(obj, "data"):
            return bytes(obj.data), name
        if isinstance(obj, InputFile):
            buf = bytearray()
            async for chunk in obj.read(bot):
                buf.extend(chunk)
            return bytes(buf), name
        raise TelegramBadRequest(method=None, message="MAX: unsupported media source")

    # ---- methods ----
    async def _send_message(self, bot, method) -> Message:
        return await self._deliver(
            bot, method.chat_id, self._html_of(bot, method, method.text),
            mhtml.keyboard_to_max(method.reply_markup),
            notify=not getattr(method, "disable_notification", False),
            link_preview_disabled=self._link_preview_disabled(method))

    async def _send_rich(self, bot, method) -> Message:
        rich = method.rich_message or {}
        body = rich.get("html") or rich.get("markdown") or ""
        if rich.get("media") or "<tg-map" in body:
            # No rich blocks on MAX: refusing makes the streamer interleave.
            raise TelegramBadRequest(method=method, message="MAX: rich media unsupported")
        if "html" in rich:
            html = mhtml.tg_html_to_max(rich["html"])
        else:
            html = mhtml.tg_html_to_max(markup.md_to_html(rich.get("markdown") or ""))
        return await self._deliver(bot, method.chat_id, html,
                                   mhtml.keyboard_to_max(method.reply_markup),
                                   notify=not getattr(method, "disable_notification", False))

    async def _draft(self, bot, method) -> bool:
        chat_id = int(method.chat_id)
        rich = getattr(method, "rich_message", None)
        raw = (rich.get("html") or rich.get("markdown") or "") if rich else (method.text or "")
        plain = mhtml.strip_tags(raw.replace("<br>", "\n").replace("<br/>", "\n")).strip()
        if not plain:                                   # empty draft clears the indicator
            entry = self._placeholders.pop(chat_id, None)
            if entry:
                await self._delete_quiet(entry[0])
            return True
        if chat_id in self._placeholders:               # later drafts are ignored
            return True
        mid = await self._post(chat_id, {"text": _THINKING_PREFIX + plain}, notify=False)
        self._placeholders[chat_id] = (mid, time.monotonic())
        return True

    def _mid_or_raise(self, method) -> str:
        mid = self.mids.mid_of(method.message_id) if method.message_id is not None else None
        if mid is None:
            raise TelegramBadRequest(method=method, message="MAX: message to edit not found")
        return mid

    async def _edit_text(self, bot, method) -> Message:
        mid = self._mid_or_raise(method)
        rich = getattr(method, "rich_message", None)
        if rich is not None:
            html = (mhtml.tg_html_to_max(rich["html"]) if "html" in rich
                    else mhtml.tg_html_to_max(markup.md_to_html(rich.get("markdown") or "")))
        else:
            html = self._html_of(bot, method, method.text)
        chunk = mhtml.split_html(html)[0] if html else ""
        kb = mhtml.keyboard_to_max(method.reply_markup)
        # An edit without `reply_markup` drops the keyboard, so `[]` clears.
        body = {"text": chunk or None, "format": "html" if chunk else None,
                "attachments": [kb] if kb else []}
        await self._edit(mid, body)
        entry = self._placeholders.get(int(method.chat_id))
        if entry and entry[0] == mid:        # caller edited the indicator itself
            self._placeholders.pop(int(method.chat_id), None)
        return self._message(bot, method.chat_id, mid, mhtml.strip_tags(chunk), kb)

    async def _edit_markup(self, bot, method) -> Message:
        mid = self._mid_or_raise(method)
        prev = self._bodies.get(mid, {})
        kb = mhtml.keyboard_to_max(method.reply_markup)
        body = {"text": prev.get("text"), "format": prev.get("format"),
                "attachments": [kb] if kb else []}
        await self._edit(mid, body)
        return self._message(bot, method.chat_id, mid, mhtml.strip_tags(prev.get("text") or ""), kb)

    async def _delete(self, bot, method) -> bool:
        mid = self.mids.mid_of(method.message_id)
        if mid is None:
            raise TelegramBadRequest(method=method, message="MAX: message to delete not found")
        await self.api.delete_message(mid)
        self._bodies.pop(mid, None)
        entry = self._placeholders.get(int(method.chat_id))
        if entry and entry[0] == mid:
            self._placeholders.pop(int(method.chat_id), None)
        return True

    async def _answer_callback(self, bot, method) -> bool:
        cid = str(method.callback_query_id)
        if cid.startswith("max:"):
            cid = cid[4:]
        text = getattr(method, "text", None)
        try:
            await self.api.answer_callback(cid, notification=text or None)
        except MaxApiError as exc:
            # A late answer after the keyboard changed is harmless.
            logger.debug("MAX: callback answer failed: %s", exc)
        return True

    async def _upload_input(self, bot, obj, kind: str) -> dict:
        """Convert an aiogram photo/document argument to a MAX attachment request."""
        if isinstance(obj, str):
            if obj.startswith("http") and kind == "image":
                return {"type": "image", "payload": {"url": obj}}
            raise TelegramBadRequest(method=None, message="MAX: file_id re-use unsupported")
        data, name = await self._bytes_of(bot, obj)
        token = await self.api.upload(kind, data, name)
        return {"type": kind, "payload": {"token": token}}

    async def _send_photo(self, bot, method) -> Message:
        att = await self._upload_input(bot, method.photo, "image")
        return await self._deliver(bot, method.chat_id, self._html_of(bot, method, method.caption),
                                   mhtml.keyboard_to_max(method.reply_markup), media=[att],
                                   notify=not getattr(method, "disable_notification", False))

    async def _send_document(self, bot, method) -> Message:
        att = await self._upload_input(bot, method.document, "file")
        return await self._deliver(bot, method.chat_id, self._html_of(bot, method, method.caption),
                                   mhtml.keyboard_to_max(method.reply_markup), media=[att],
                                   notify=not getattr(method, "disable_notification", False))

    async def _send_location(self, bot, method) -> Message:
        att = {"type": "location", "latitude": float(method.latitude),
               "longitude": float(method.longitude)}
        parts = [getattr(method, "title", None), getattr(method, "address", None)]
        caption = "\n".join(markup.escape_html(p) for p in parts if p)
        return await self._deliver(bot, method.chat_id, caption,
                                   mhtml.keyboard_to_max(method.reply_markup), media=[att])

    async def _chat_action(self, bot, method) -> bool:
        chat = self.chat_of_user.get(int(method.chat_id))
        if chat is not None:
            with contextlib.suppress(MaxApiError):
                await self.api.send_action(chat, "typing_on")
        return True

    async def _set_commands(self, bot, method) -> bool:
        """Register the shared command menu on MAX's single global list.

        - MAX has no per-chat scopes and no per-language lists
        - The default-scope call registers every in-menu non-owner command
        - Scoped and localized calls are acknowledged and dropped
        """
        scope = getattr(method, "scope", None)
        if getattr(method, "language_code", None) or (
                scope is not None and getattr(scope, "type", "default") != "default"):
            return True
        cmds = [{"name": slug, "description": desc} for slug, desc in max_command_list()]
        await self.api.patch_commands(cmds)
        return True

    async def _get_me(self, bot, method) -> User:
        me = await self.api.get_me()
        self.bot_user = me
        return User.model_validate({
            "id": to_internal(me["user_id"]), "is_bot": True,
            "first_name": me.get("first_name") or me.get("name") or "bot",
            "username": me.get("username")}, context={"bot": bot})

    async def _get_file(self, bot, method) -> File:
        rf = self.files.get(method.file_id)
        if rf is None:
            raise TelegramBadRequest(method=method, message="MAX: unknown file id")
        return File.model_validate({"file_id": method.file_id, "file_unique_id": method.file_id,
                                    "file_size": rf.size,
                                    "file_path": FileRegistry.path_of(method.file_id)},
                                   context={"bot": bot})


def max_command_list(lang: str | None = None) -> list[tuple[str, str]]:
    """(slug, description) pairs for the MAX command list.

    - Shared in-menu commands, no owner ones, capped at 32
    """
    from app import i18n
    from app.telegram import commands

    lang = lang or i18n.DEFAULT_LANG
    by = commands.by_slug()
    out: list[tuple[str, str]] = []
    for slug in commands.menu_slugs():
        cmd = by.get(slug)
        if cmd is None or cmd.scope == "owner":
            continue
        out.append((slug, (cmd.label.get(lang) or cmd.label["en"])[:128]))
    return out[:COMMANDS_LIMIT]


def guess_mime(name: str | None) -> str | None:
    return mimetypes.guess_type(name)[0] if name else None


class RoutingSession(BaseSession):
    """One `bot.session` for Telegram and MAX.

    - MAX-namespace addresses go to MAX; `setMyCommands` goes to both
    """

    def __init__(self, telegram: BaseSession, max_session: MaxSession | None) -> None:
        super().__init__(api=telegram.api, json_loads=telegram.json_loads,
                         json_dumps=telegram.json_dumps, timeout=telegram.timeout)
        self.telegram = telegram
        self.max = max_session

    def route(self, method) -> str:
        if self.max is None:
            return "tg"
        name = method.__api_method__
        if name == "setMyCommands":
            return "both"
        chat_id = getattr(method, "chat_id", None)
        if chat_id is not None and is_internal_max(chat_id):
            return "max"
        cq = getattr(method, "callback_query_id", None)
        if isinstance(cq, str) and cq.startswith("max:"):
            return "max"
        fid = getattr(method, "file_id", None)
        if FileRegistry.is_max(fid):
            return "max"
        uid = getattr(method, "user_id", None)
        if uid is not None and chat_id is None and is_internal_max(uid):
            return "max"
        return "tg"

    def embeds_rich_media(self, chat_id) -> bool:
        """False for a MAX chat: no rich blocks there."""
        return self.max is None or not is_internal_max(chat_id)

    async def make_request(self, bot, method, timeout=None):
        where = self.route(method)
        if where == "max":
            return await self.max.make_request(bot, method, timeout)
        if where == "both":
            result = await self.telegram.make_request(bot, method, timeout)
            try:
                await self.max.make_request(bot, method, timeout)
            except Exception as exc:        # MAX failure must not fail Telegram call
                logger.warning("MAX: %s not applied: %s", method.__api_method__, exc)
            return result
        return await self.telegram.make_request(bot, method, timeout)

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536,
                             raise_for_status=True):
        if self.max is not None and "/max/" in url:
            async for chunk in self.max.stream_content(url, headers, timeout, chunk_size,
                                                       raise_for_status):
                yield chunk
            return
        async for chunk in self.telegram.stream_content(url, headers=headers, timeout=timeout,
                                                        chunk_size=chunk_size,
                                                        raise_for_status=raise_for_status):
            yield chunk

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.telegram.close()
        if self.max is not None:
            with contextlib.suppress(Exception):
                await self.max.close()
