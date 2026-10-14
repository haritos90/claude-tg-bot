"""MAX long-poller producing synthetic aiogram updates.

- `GET /updates` long poll, 30 s window
- Each update becomes an aiogram `Update` for the `Dispatcher`
- Several images become one message each, sharing a `media_group_id`
- Groups and channels are ignored; DM only
- Poll marker persists in kv `max_marker`
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from aiogram.types import Update

from app.max.bridge import MaxSession, guess_mime
from app.max.client import MaxApi, MaxApiError
from app.max.ids import to_internal
from app.storage import db

logger = logging.getLogger(__name__)

MARKER_KEY = "max_marker"
UPDATE_TYPES = ["message_created", "message_callback", "bot_started"]
_BACKOFF = (2, 5, 10, 20, 30)


class MaxPoller:
    def __init__(self, api: MaxApi, bridge: MaxSession, dp, bot) -> None:
        self.api = api
        self.bridge = bridge
        self.dp = dp
        self.bot = bot
        self._update_seq = int(time.time())
        self._tasks: set[asyncio.Task] = set()

    # ---- loop ----
    async def run(self) -> None:
        marker: int | None = None
        with contextlib.suppress(Exception):
            raw = await db.get_kv(MARKER_KEY)
            marker = int(raw) if raw else None
        fails = 0
        logger.info("MAX: polling started (marker=%s)", marker)
        while True:
            try:
                data = await self.api.get_updates(marker, timeout=30, types=UPDATE_TYPES)
                fails = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = _BACKOFF[min(fails, len(_BACKOFF) - 1)]
                fails += 1
                level = logging.WARNING if fails in (1, 10, 100) else logging.DEBUG
                logger.log(level, "MAX: get_updates failed (%s); retry in %ss", exc, delay)
                await asyncio.sleep(delay)
                continue
            for upd in data.get("updates") or []:
                self._spawn(upd)
            new_marker = data.get("marker")
            if new_marker is not None and new_marker != marker:
                marker = new_marker
                with contextlib.suppress(Exception):
                    await db.set_kv(MARKER_KEY, str(marker))

    def _spawn(self, upd: dict) -> None:
        task = asyncio.create_task(self._handle(upd))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(self, upd: dict) -> None:
        try:
            for data in self.to_updates(upd):
                update = Update.model_validate(data, context={"bot": self.bot})
                await self.dp.feed_update(self.bot, update)
        except MaxApiError as exc:
            logger.warning("MAX: update handling failed: %s", exc)
        except Exception:
            logger.exception("MAX: unhandled error while processing an update")

    # ---- conversion ----
    def _next_update_id(self) -> int:
        self._update_seq += 1
        return self._update_seq

    @staticmethod
    def _user(u: dict | None, locale: str | None = None) -> dict | None:
        if not u or u.get("user_id") is None:
            return None
        out = {"id": to_internal(u["user_id"]), "is_bot": bool(u.get("is_bot")),
               "first_name": u.get("first_name") or u.get("name") or "—",
               "last_name": u.get("last_name"), "username": u.get("username")}
        if locale:
            out["language_code"] = str(locale)
        return out

    @staticmethod
    def _chat(user: dict) -> dict:
        return {"id": user["id"], "type": "private", "first_name": user.get("first_name"),
                "last_name": user.get("last_name"), "username": user.get("username")}

    def _base_message(self, msg: dict, sender: dict, chat: dict, ts: int | None) -> dict:
        mid = ((msg.get("body") or {}).get("mid")) or f"nomid:{time.time_ns()}"
        return {"message_id": self.bridge.mids.int_of(mid),
                "date": int((ts or msg.get("timestamp") or time.time() * 1000) // 1000),
                "chat": chat, "from": sender}

    def to_updates(self, upd: dict) -> list[dict]:
        """One MAX update to zero or more aiogram `Update` dicts.

        - Pure function
        """
        kind = upd.get("update_type")
        if kind == "message_created":
            return self._from_message_created(upd)
        if kind == "message_callback":
            return self._from_callback(upd)
        if kind == "bot_started":
            return self._from_bot_started(upd)
        return []

    def _from_message_created(self, upd: dict) -> list[dict]:
        msg = upd.get("message") or {}
        recipient = msg.get("recipient") or {}
        if recipient.get("chat_type") not in (None, "dialog"):
            return []                                    # groups/channels: not a live surface
        sender = self._user(msg.get("sender"), upd.get("user_locale"))
        if sender is None or sender["is_bot"]:
            return []
        if recipient.get("chat_id") is not None:
            self.bridge.chat_of_user[sender["id"]] = int(recipient["chat_id"])
        chat = self._chat(sender)
        body = msg.get("body") or {}
        text = body.get("text") or ""
        base = self._base_message(msg, sender, chat, upd.get("timestamp"))
        images: list[dict] = []
        extra: dict[str, Any] = {}
        for att in body.get("attachments") or []:
            t = att.get("type")
            payload = att.get("payload") or {}
            if t == "image" and payload.get("url"):
                images.append(payload)
            elif t == "file" and payload.get("url") and "document" not in extra:
                name = att.get("filename")
                fid = self.bridge.files.register(payload["url"], name, att.get("size"),
                                                 guess_mime(name))
                extra["document"] = {"file_id": fid, "file_unique_id": fid, "file_name": name,
                                     "mime_type": guess_mime(name), "file_size": att.get("size")}
            elif t == "audio" and payload.get("url") and "voice" not in extra:
                fid = self.bridge.files.register(payload["url"], "audio", None, "audio/mp4")
                extra["voice"] = {"file_id": fid, "file_unique_id": fid, "duration": 0}
            elif t == "location" and att.get("latitude") is not None:
                extra["location"] = {"latitude": att["latitude"], "longitude": att["longitude"]}
        out: list[dict] = []
        if images:
            group = str(base["message_id"]) if len(images) > 1 else None
            for i, payload in enumerate(images):
                fid = self.bridge.files.register(payload["url"], "photo.jpg", None, "image/jpeg")
                m = dict(base)
                if i:
                    m["message_id"] = self.bridge.mids.int_of(f"{payload.get('token') or fid}")
                m["photo"] = [{"file_id": fid, "file_unique_id": fid, "width": 0, "height": 0}]
                if i == 0 and text:
                    m["caption"] = text
                if group:
                    m["media_group_id"] = group
                out.append({"update_id": self._next_update_id(), "message": m})
            if extra:
                m = dict(base, **extra)
                m["message_id"] = self.bridge.mids.int_of(f"extra:{base['message_id']}")
                out.append({"update_id": self._next_update_id(), "message": m})
            return out
        m = dict(base, **extra)
        if extra and text:
            m["caption"] = text
        elif text:
            m["text"] = text
        elif not extra:
            return []                                    # sticker/contact/video only: ignore
        return [{"update_id": self._next_update_id(), "message": m}]

    def _from_callback(self, upd: dict) -> list[dict]:
        cb = upd.get("callback") or {}
        user = self._user(cb.get("user"), upd.get("user_locale"))
        if user is None or not cb.get("callback_id"):
            return []
        chat = self._chat(user)
        message = None
        src = upd.get("message")
        if src:
            recipient = src.get("recipient") or {}
            if recipient.get("chat_id") is not None:
                self.bridge.chat_of_user[user["id"]] = int(recipient["chat_id"])
            me = self.bridge.bot_user or {}
            bot_user = {"id": to_internal(me.get("user_id", 0)), "is_bot": True,
                        "first_name": me.get("first_name") or "bot", "username": me.get("username")}
            message = self._base_message(src, bot_user, chat, upd.get("timestamp"))
            message["text"] = (src.get("body") or {}).get("text") or None
        data = {"id": f"max:{cb['callback_id']}", "from": user, "chat_instance": str(chat["id"]),
                "data": cb.get("payload")}
        if message is not None:
            data["message"] = message
        return [{"update_id": self._next_update_id(), "callback_query": data}]

    def _from_bot_started(self, upd: dict) -> list[dict]:
        user = self._user(upd.get("user"), upd.get("user_locale"))
        if user is None:
            return []
        if upd.get("chat_id") is not None:
            self.bridge.chat_of_user[user["id"]] = int(upd["chat_id"])
        chat = self._chat(user)
        m = {"message_id": self.bridge.mids.int_of(f"start:{time.time_ns()}"),
             "date": int((upd.get("timestamp") or time.time() * 1000) // 1000),
             "chat": chat, "from": user, "text": "/start",
             "entities": [{"type": "bot_command", "offset": 0, "length": 6}]}
        return [{"update_id": self._next_update_id(), "message": m}]
