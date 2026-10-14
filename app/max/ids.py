"""Identity namespace and id registries for the MAX transport.

- MAX users map to internal id `MAX_ID_OFFSET + max_user_id`
- Telegram ids sit far below the offset
- `MidRegistry` maps string mids to process-local ints
- `FileRegistry` maps attachment URLs to `max:<n>` file ids
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_ID_OFFSET = 1_000_000_000_000  # above Telegram ids, below 2**52


def to_internal(max_id: int) -> int:
    """MAX user/chat id to the internal bot id."""
    return MAX_ID_OFFSET + int(max_id)


def is_internal_max(uid) -> bool:
    """True if an internal id belongs to the MAX namespace."""
    try:
        return int(uid) >= MAX_ID_OFFSET
    except (TypeError, ValueError):
        return False


def to_max(uid: int) -> int:
    """Internal id back to the MAX user id."""
    return int(uid) - MAX_ID_OFFSET


class MidRegistry:
    """Bidirectional map between MAX string message ids and local ints.

    - Ints are meaningful only within this process
    - Reverse lookup serves edits and deletes
    """

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
    """`max:<n>` file ids for incoming attachment URLs.

    - Bounded; oldest dropped
    """

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
        """The `file_path` handed to aiogram, spotted by `RoutingSession.stream_content`."""
        return "max/" + file_id.split(":", 1)[1]

    def by_path(self, path: str) -> RemoteFile | None:
        tail = path.rsplit("max/", 1)[-1]
        return self._files.get("max:" + tail)
