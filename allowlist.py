"""A small, dependency-free allowlist backed by a JSON file.

Access is granted when the user is the owner, or when their numeric id (or, until
pinned, their ``@username``) has an allowlist **entry** that has not expired.
Numeric ids are authoritative; usernames are a convenience that is upgraded to an
id on first contact (``pin``).

Each entry carries per-user access metadata (one rewrite serving #102/#103/#105):

- ``level``       — ``"chat"`` (may only use chat sessions) or ``"code"`` (chat + code).
- ``expires_at``  — an ISO date (``YYYY-MM-DD``) / datetime, or ``None`` for never.
- ``token_grant`` — a cumulative token allowance (``None`` = unlimited). "Used" is
  computed elsewhere (aggregate ``db.usage``); ``remaining = grant - used``.

On-disk JSON (version 2)::

    {
      "version": 2,
      "entries": {"<id>": {"username": <str|null>, "level": "chat|code",
                            "expires_at": <str|null>, "token_grant": <int|null>}},
      "pending_usernames": {"<name>": {"level": ..., "expires_at": ...,
                                       "token_grant": ...}}
    }

A **legacy** ``{"ids": [...], "usernames": [...]}`` file is migrated in memory to
``level="code"`` / no expiry / no cap (preserving prior behaviour) and persisted in
the new shape on the next mutation.

The allowlist **never fails open**: a missing/corrupt file means owner-only; a
corrupt single record degrades to the least-privileged ``chat`` level; an
unparseable expiry is treated as expired (denied). The owner is NEVER written to
the file — it is synthesised in memory as ``level=code``, never expires, never
capped.

All public methods are synchronous; the file reloads lazily on mtime change and
writes are atomic (temp file + ``os.replace``).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Telegram-ish username pattern (after stripping a leading "@" and lowercasing).
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")

LEVELS = ("chat", "code")


def _norm_username(name: str) -> str:
    """Lowercase a username and strip a single leading ``@``."""
    return name.strip().lstrip("@").lower()


def _utcnow() -> datetime:
    """Current UTC time (the access clock is UTC; documented for #103)."""
    return datetime.now(timezone.utc)


def normalize_date(s: str) -> Optional[str]:
    """Validate an expiry the owner typed and return a canonical ``YYYY-MM-DD``
    string, or ``None`` if it is not a usable date. Accepts ``never``/``none``/
    ``off`` (→ ``None``) so callers can clear an expiry."""
    s = (s or "").strip().lower()
    if s in ("", "never", "none", "off", "unlimited"):
        return None
    try:
        # Accept a plain date or a full ISO timestamp; store the date part.
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


class Allowlist:
    """JSON-backed allowlist with owner override, per-entry metadata, and lazy
    reload. Fail-closed at every layer."""

    def __init__(self, path, owner_id: int) -> None:
        self.path = Path(path)
        self.owner_id = owner_id
        self._entries: dict[int, dict] = {}   # id   -> {username, level, expires_at, token_grant}
        self._pending: dict[str, dict] = {}   # name -> {level, expires_at, token_grant}
        self._mtime: Optional[float] = None
        self._load()

    # -- normalisation ------------------------------------------------------

    @staticmethod
    def _norm_level(v) -> str:
        # Anything that is not exactly "code" degrades to the least-privileged
        # "chat" — a corrupt/unknown level must never grant code access.
        return "code" if v == "code" else "chat"

    @staticmethod
    def _norm_expiry(v) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @staticmethod
    def _norm_grant(v) -> Optional[int]:
        if v is None:
            return None
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return None

    def _norm_record(self, rec: Optional[dict]) -> dict:
        rec = rec or {}
        uname = rec.get("username")
        uname = _norm_username(str(uname)) if uname else None
        return {
            "username": uname or None,
            "level": self._norm_level(rec.get("level")),
            "expires_at": self._norm_expiry(rec.get("expires_at")),
            "token_grant": self._norm_grant(rec.get("token_grant")),
        }

    def _norm_pending(self, rec: Optional[dict]) -> dict:
        rec = rec or {}
        return {
            "level": self._norm_level(rec.get("level")),
            "expires_at": self._norm_expiry(rec.get("expires_at")),
            "token_grant": self._norm_grant(rec.get("token_grant")),
        }

    # -- loading / saving ---------------------------------------------------

    def _load(self) -> None:
        """(Re)load state from disk. On any error, reset to empty (owner-only)."""
        try:
            mtime = self.path.stat().st_mtime
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            entries: dict[int, dict] = {}
            pending: dict[str, dict] = {}
            if isinstance(data, dict) and ("entries" in data or "version" in data):
                for sid, rec in (data.get("entries") or {}).items():
                    try:
                        uid = int(sid)
                    except (TypeError, ValueError):
                        continue
                    if uid == self.owner_id:
                        continue  # owner is synthesised, never stored
                    entries[uid] = self._norm_record(rec)
                for name, rec in (data.get("pending_usernames") or {}).items():
                    n = _norm_username(str(name))
                    if n:
                        pending[n] = self._norm_pending(rec)
            else:
                # Legacy {ids, usernames}: migrate as level=code / no expiry / no cap.
                for i in data.get("ids", []):
                    try:
                        uid = int(i)
                    except (TypeError, ValueError):
                        continue
                    if uid == self.owner_id:
                        continue
                    entries[uid] = {"username": None, "level": "code",
                                    "expires_at": None, "token_grant": None}
                for u in data.get("usernames", []):
                    n = _norm_username(str(u))
                    if n:
                        pending[n] = {"level": "code", "expires_at": None,
                                      "token_grant": None}
            self._entries = entries
            self._pending = pending
            self._mtime = mtime
        except Exception:
            self._entries = {}
            self._pending = {}
            self._mtime = None

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self._load()

    def _save(self) -> None:
        payload = {
            "version": 2,
            "entries": {str(uid): rec for uid, rec in sorted(self._entries.items())},
            "pending_usernames": {n: rec for n, rec in sorted(self._pending.items())},
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = None

    # -- queries ------------------------------------------------------------

    def _find(self, user_id: Optional[int], username: Optional[str]) -> Optional[dict]:
        """The record for this user (entry by id, else pending by username), or None."""
        if user_id is not None and user_id in self._entries:
            return self._entries[user_id]
        if username is not None:
            n = _norm_username(username)
            if n in self._pending:
                return self._pending[n]
        return None

    def _is_expired(self, rec: dict) -> bool:
        exp = rec.get("expires_at")
        if not exp:
            return False
        try:
            s = str(exp)
            if len(s) <= 10:
                # Date-only: access is valid THROUGH that calendar day (UTC).
                return _utcnow().date() > date.fromisoformat(s)
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return _utcnow() > dt
        except Exception:
            # Unparseable expiry → fail closed (treat as expired / denied).
            return True

    def is_allowed(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """``True`` iff the user is the owner, or has a non-expired entry.
        ``None``-safe; never allows all."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return True
        rec = self._find(user_id, username)
        return rec is not None and not self._is_expired(rec)

    def level_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[str]:
        """The user's access level (``"chat"``/``"code"``), or ``None`` if not
        allowed (or expired). Owner is always ``"code"``."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return "code"
        rec = self._find(user_id, username)
        if rec is None or self._is_expired(rec):
            return None
        return self._norm_level(rec.get("level"))

    def token_grant_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[int]:
        """The user's cumulative token grant (``None`` = unlimited). Owner is
        always unlimited."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return None
        rec = self._find(user_id, username)
        if rec is None:
            return None
        return self._norm_grant(rec.get("token_grant"))

    def pin(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Upgrade a username-only match to a stable numeric id, CARRYING its
        record (level/expiry/grant). Also refreshes a known entry's username.
        Returns ``True`` if a pin (new id) was performed."""
        self._reload_if_changed()
        if user_id is None or user_id == self.owner_id:
            # Owner is synthesised, never stored. Clean up a legacy-migrated pending
            # entry for the owner's OWN username (cosmetic — owner access is by id).
            if user_id == self.owner_id and username:
                n = _norm_username(username)
                if n in self._pending:
                    del self._pending[n]
                    self._save()
            return False
        if user_id in self._entries:
            if username:
                n = _norm_username(username)
                if n and self._entries[user_id].get("username") != n:
                    self._entries[user_id]["username"] = n
                    self._save()
            return False
        if username is None:
            return False
        n = _norm_username(username)
        if n not in self._pending:
            return False
        rec = self._pending.pop(n)
        rec["username"] = n
        self._entries[user_id] = self._norm_record(rec)
        self._save()
        return True

    # -- mutations ----------------------------------------------------------

    def _record_for_target(self, target: str) -> Optional[dict]:
        """The mutable record for an id-or-username target, or None if absent."""
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        if candidate.isascii() and candidate.isdigit():
            return self._entries.get(int(raw))
        return self._pending.get(_norm_username(raw))

    def add(
        self,
        target: str,
        level: Optional[str] = None,
        expires_at: Optional[str] = None,
        token_grant: Optional[int] = None,
    ) -> tuple[str, str]:
        """Grant access to an id or username. ``level`` defaults to ``"chat"``
        (least privilege, #102). ``expires_at`` / ``token_grant`` are applied only
        when provided (so re-granting with just a level keeps an existing expiry /
        grant). Returns ``("id"|"username"|"invalid"|"owner", value)``."""
        self._reload_if_changed()
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        lvl = self._norm_level(level) if level else "chat"
        if candidate.isascii() and candidate.isdigit():
            uid = int(raw)
            if uid == self.owner_id:
                return ("owner", str(uid))  # always allowed; nothing to store
            rec = self._entries.get(uid) or {
                "username": None, "level": "chat", "expires_at": None, "token_grant": None
            }
            rec["level"] = lvl
            if expires_at is not None:
                rec["expires_at"] = self._norm_expiry(expires_at)
            if token_grant is not None:
                rec["token_grant"] = self._norm_grant(token_grant)
            self._entries[uid] = self._norm_record(rec)
            self._save()
            return ("id", str(uid))
        name = _norm_username(raw)
        if not _USERNAME_RE.match(name):
            return ("invalid", raw)
        rec = self._pending.get(name) or {
            "level": "chat", "expires_at": None, "token_grant": None
        }
        rec["level"] = lvl
        if expires_at is not None:
            rec["expires_at"] = self._norm_expiry(expires_at)
        if token_grant is not None:
            rec["token_grant"] = self._norm_grant(token_grant)
        self._pending[name] = self._norm_pending(rec)
        self._save()
        return ("username", name)

    def set_level(self, target: str, level: str) -> bool:
        """Change an existing entry's level. Returns True if the target exists."""
        self._reload_if_changed()
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["level"] = self._norm_level(level)
        self._save()
        return True

    def set_expiry(self, target: str, expires_at: Optional[str]) -> bool:
        """Set/clear an existing entry's expiry. Returns True if the target exists."""
        self._reload_if_changed()
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["expires_at"] = self._norm_expiry(expires_at)
        self._save()
        return True

    def grant_tokens(self, target: str, tokens: Optional[int]) -> bool:
        """Add ``tokens`` to the target's cumulative grant (``tokens=None`` →
        unlimited). Returns True if the target exists."""
        self._reload_if_changed()
        rec = self._record_for_target(target)
        if rec is None:
            return False
        if tokens is None:
            rec["token_grant"] = None
        else:
            rec["token_grant"] = (rec.get("token_grant") or 0) + max(0, int(tokens))
        self._save()
        return True

    def remove(self, target: str) -> bool:
        """Remove a matching id or username (also drops an id-entry whose stored
        username matches, so ``/deny @name`` works after the user was pinned).
        Returns ``True`` if anything was removed."""
        self._reload_if_changed()
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        removed = False
        if candidate.isascii() and candidate.isdigit():
            uid = int(raw)
            if uid in self._entries:
                del self._entries[uid]
                removed = True
        else:
            name = _norm_username(raw)
            if name in self._pending:
                del self._pending[name]
                removed = True
            for uid, rec in list(self._entries.items()):
                if rec.get("username") == name:
                    del self._entries[uid]
                    removed = True
        if removed:
            self._save()
        return removed

    def snapshot(self) -> dict:
        """A stable, sorted view of the current allowlist (feeds ``/users``)."""
        self._reload_if_changed()
        return {
            "owner_id": self.owner_id,
            "entries": {uid: dict(rec) for uid, rec in sorted(self._entries.items())},
            "pending": {n: dict(rec) for n, rec in sorted(self._pending.items())},
        }
