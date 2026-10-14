"""Identity namespace and id registries for the MAX transport (#434).

Every store in the bot (sessions, allowlist, usage, kv per-user keys, the i18n cache, the
owner check) keys users by one bare integer, and a DM's chat id doubles as the user id.
MAX user ids are small positive integers like Telegram's, so a MAX user is mapped to an
INTERNAL id ``MAX_ID_OFFSET + max_user_id`` before it enters the dispatcher. Telegram user
ids are far below the offset (they fit in 52 bits but are ~1e10 today), so the two spaces
never meet: a MAX user can never collide with, or be mistaken for, a Telegram user — in
particular never for the owner. Sessions and users are therefore completely separate per
platform by construction; the owner's MAX account is an ordinary allowlisted user.

MAX message ids are opaque strings (``mid.…``) while aiogram wants an int ``message_id``;
``MidRegistry`` hands out process-local ints. ``FileRegistry`` does the same for incoming
attachment URLs behind a ``max:<n>`` file_id, so ``bot.download()`` works unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_ID_OFFSET = 1_000_000_000_000  # 1e12: above any Telegram id, far below 2**52


def to_internal(max_id: int) -> int:
    """MAX user/chat id → the internal id used everywhere inside the bot."""
    return MAX_ID_OFFSET + int(max_id)


def is_internal_max(uid) -> bool:
    """True when an internal id (user or DM chat) belongs to the MAX namespace."""
    try:
        return int(uid) >= MAX_ID_OFFSET
    except (TypeError, ValueError):
        return False


def to_max(uid: int) -> int:
    """Internal id → the MAX user id it was mapped from."""
    return int(uid) - MAX_ID_OFFSET


class MidRegistry:
    """Bidirectional map between MAX string message ids and process-local ints.

    Ints are only meaningful for this process (a restart forgets them) — that matches how
    the bot already treats Telegram message ids it keeps in memory. The reverse lookup is
    what edits/deletes need; a callback carries its message's mid, so a button on a message
    sent before a restart still resolves."""

    def __init__(self) -> None:
        self._by_mid: dict[str, int] = {}
        self._by_int: dict[int, str] = {}
        self._next = 1

    def int_of(self, mid: str) -> int:
        n = self._by_mid.get(mid)
        if n is None:
            n = self._next
            self._next += 1
            self._by_mid[mid] = n
            self._by_int[n] = mid
        return n

    def mid_of(self, n: int) -> str | None:
        return self._by_int.get(int(n))

    def forget(self, mid: str) -> None:
        n = self._by_mid.pop(mid, None)
        if n is not None:
            self._by_int.pop(n, None)


@dataclass
class RemoteFile:
    url: str
    name: str | None = None
    size: int | None = None
    mime: str | None = None


class FileRegistry:
    """``max:<n>`` file ids for incoming attachment URLs (bounded; oldest dropped)."""

    def __init__(self, cap: int = 2048) -> None:
        self._files: dict[str, RemoteFile] = {}
        self._cap = cap
        self._next = 1

    def register(self, url: str, name: str | None = None, size: int | None = None,
                 mime: str | None = None) -> str:
        fid = f"max:{self._next}"
        self._next += 1
        self._files[fid] = RemoteFile(url=url, name=name, size=size, mime=mime)
        while len(self._files) > self._cap:
            self._files.pop(next(iter(self._files)))
        return fid

    def get(self, file_id: str) -> RemoteFile | None:
        return self._files.get(file_id)

    @staticmethod
    def is_max(file_id) -> bool:
        return isinstance(file_id, str) and file_id.startswith("max:")

    @staticmethod
    def path_of(file_id: str) -> str:
        """The ``file_path`` handed to aiogram; ``RoutingSession.stream_content`` spots it."""
        return "max/" + file_id.split(":", 1)[1]

    def by_path(self, path: str) -> RemoteFile | None:
        tail = path.rsplit("max/", 1)[-1]
        return self._files.get("max:" + tail)
