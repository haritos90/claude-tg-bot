"""Thin async client for the MAX Platform API.

- Base URL `https://platform-api2.max.ru`; token in `Authorization`
- TLS trusts system store plus bundled Russian root
- The extra root is scoped to this client
- Uploads: `POST /uploads`, multipart data, attach by token
- `send_message` retries `attachment.not.ready`; pacing stays under ~30 rps
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from pathlib import Path
from typing import Any

import aiohttp

from app import DEPLOY_DIR

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://platform-api2.max.ru"
BUNDLED_CA = DEPLOY_DIR / "certs" / "russian_trusted_root_ca.pem"
TEXT_LIMIT = 4000          # NewMessageBody.text maxLength
BUTTON_TEXT_LIMIT = 128    # Button.text maxLength
CALLBACK_PAYLOAD_LIMIT = 1024
COMMANDS_LIMIT = 32        # BotCommandsPatch.commands maxItems
_MIN_INTERVAL = 1 / 25     # stay under 30 rps limit
_NOT_READY_DELAYS = (0.5, 1.0, 2.0, 4.0)


class MaxApiError(Exception):
    """A non-2xx platform reply; `code` is the platform's error code."""

    def __init__(self, status: int, code: str, message: str, method: str = ""):
        super().__init__(f"{method} -> {status} {code}: {message}".strip())
        self.status = status
        self.code = code
        self.message = message


def ssl_context(ca_bundle: str | Path | None) -> ssl.SSLContext | bool:
    """System trust store plus the bundled Russian root.

    - `"system"` returns the plain default context
    """
    if ca_bundle == "system":
        return True
    ctx = ssl.create_default_context()
    path = Path(ca_bundle) if ca_bundle else BUNDLED_CA
    try:
        ctx.load_verify_locations(cafile=str(path))
    except (OSError, ssl.SSLError):
        logger.error("MAX: cannot load CA bundle %s; TLS to the API will fail", path)
    return ctx


class MaxApi:
    def __init__(self, token: str, base: str = DEFAULT_BASE,
                 ca_bundle: str | Path | None = None, timeout: float = 40.0) -> None:
        self._token = token
        self.base = (base or DEFAULT_BASE).rstrip("/")
        self._ssl = ssl_context(ca_bundle)
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._pace = asyncio.Lock()
        self._last = 0.0

    # ---- plumbing ----
    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _paced(self) -> None:
        async with self._pace:
            wait = self._last + _MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: Any = None, timeout: float | None = None) -> Any:
        """One API call returning decoded JSON (`{}` if empty).

        - 429 is retried a few times
        - Other non-2xx raise `MaxApiError`; the token is never logged
        """
        sess = await self.session()
        url = self.base + path
        headers = {"Authorization": self._token}
        params = {k: (str(v).lower() if isinstance(v, bool) else v)
                  for k, v in (params or {}).items() if v is not None}
        kw: dict[str, Any] = {"params": params, "headers": headers}
        if json is not None:
            kw["json"] = json
        if timeout is not None:
            kw["timeout"] = aiohttp.ClientTimeout(total=timeout)
        for attempt in range(4):
            await self._paced()
            async with sess.request(method, url, **kw) as resp:
                if resp.status == 429 and attempt < 3:
                    await asyncio.sleep(1.0 + attempt)
                    continue
                raw = await resp.read()
                data: Any = {}
                if raw:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw": raw[:200].decode("utf-8", "replace")}
                if resp.status >= 400:
                    code = str((data or {}).get("code") or resp.status) if isinstance(data, dict) else str(resp.status)
                    msg = str((data or {}).get("message") or data) if isinstance(data, dict) else str(data)
                    raise MaxApiError(resp.status, code, msg, f"{method} {path}")
                return data
        raise MaxApiError(429, "too.many.requests", "rate limited", f"{method} {path}")

    # ---- methods ----
    async def get_me(self) -> dict:
        return await self.request("GET", "/me")

    async def patch_commands(self, commands: list[dict]) -> dict:
        return await self.request("PATCH", "/me/commands",
                                  json={"commands": commands[:COMMANDS_LIMIT]})

    async def get_updates(self, marker: int | None, timeout: int = 30, limit: int = 100,
                          types: list[str] | None = None) -> dict:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        # The HTTP timeout must outlive the server long-poll window.
        return await self.request("GET", "/updates", params=params, timeout=timeout + 15)

    async def send_message(self, *, user_id: int | None = None, chat_id: int | None = None,
                           body: dict, disable_link_preview: bool | None = None) -> dict:
        """`POST /messages` returning the created `Message` dict.

        - Retries the `attachment.not.ready` race
        """
        params = {"user_id": user_id, "chat_id": chat_id,
                  "disable_link_preview": disable_link_preview}
        for delay in (*_NOT_READY_DELAYS, None):
            try:
                data = await self.request("POST", "/messages", params=params, json=body)
                return data.get("message") or {}
            except MaxApiError as exc:
                if exc.code == "attachment.not.ready" and delay is not None:
                    await asyncio.sleep(delay)
                    continue
                raise
        return {}

    async def edit_message(self, mid: str, body: dict) -> None:
        await self.request("PUT", "/messages", params={"message_id": mid}, json=body)

    async def delete_message(self, mid: str) -> None:
        await self.request("DELETE", "/messages", params={"message_id": mid})

    async def answer_callback(self, callback_id: str, *, notification: str | None = None,
                              message: dict | None = None) -> None:
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        await self.request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def send_action(self, chat_id: int, action: str = "typing_on") -> None:
        await self.request("POST", f"/chats/{chat_id}/actions", json={"action": action})

    async def upload(self, kind: str, data: bytes, filename: str) -> str:
        """Upload `data` as `kind` and return the attachment token."""
        endpoint = await self.request("POST", "/uploads", params={"type": kind})
        url = endpoint["url"]
        sess = await self.session()
        form = aiohttp.FormData()
        form.add_field("data", data, filename=filename or "file.bin",
                       content_type="application/octet-stream")
        await self._paced()
        async with sess.post(url, data=form) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                raise MaxApiError(resp.status, "upload.failed",
                                  raw[:200].decode("utf-8", "replace"), f"upload {kind}")
        if endpoint.get("token"):            # video/audio: token comes with URL
            return endpoint["token"]
        try:
            import json as _json
            info = _json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MaxApiError(500, "upload.badreply", raw[:200].decode("utf-8", "replace"),
                              f"upload {kind}") from exc
        if kind == "image":                  # photos: id to token mapping
            photos = info.get("photos") or {}
            for entry in photos.values():
                if isinstance(entry, dict) and entry.get("token"):
                    return entry["token"]
            raise MaxApiError(500, "upload.notoken", str(info)[:200], "upload image")
        token = info.get("token")            # file: fileId and token
        if not token:
            raise MaxApiError(500, "upload.notoken", str(info)[:200], f"upload {kind}")
        return token

    async def download(self, url: str, chunk_size: int = 65536):
        """Stream an attachment URL's bytes with the same TLS context."""
        sess = await self.session()
        async with sess.get(url) as resp:
            resp.raise_for_status()
            async for chunk in resp.content.iter_chunked(chunk_size):
                yield chunk
