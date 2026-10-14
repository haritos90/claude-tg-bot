"""JSON-backed allowlist with per-user access metadata.

- Owner always has code access, never expires, never capped
- Entries hold level, expiry, rate caps, memory and effort flags
- Numeric ids are authoritative; usernames pin to ids on contact
- Never fails open: a corrupt file means owner-only
- Lazy reload on mtime; atomic writes via `os.replace`
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Telegram-style username pattern, after lowercasing and stripping `@`.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")

LEVELS = ("chat", "code")

# Sentinel: leave this field unchanged in `set_rate`.
# - Lets callers update only day or week
_UNSET = object()


def _norm_username(name: str) -> str:
    """Lowercase a username and strip one leading `@`."""
    return name.strip().lstrip("@").lower()


def _utcnow() -> datetime:
    """Current UTC time; the access clock is UTC."""
    return datetime.now(timezone.utc)


def normalize_date(s: str) -> Optional[str]:
    """Validate a typed expiry; return `YYYY-MM-DD` or `None`.

    - `never`, `none`, `off` clear the expiry
    """
    s = (s or "").strip().lower()
    if s in ("", "never", "none", "off", "unlimited"):
        return None
    try:
        # Accept a plain date or ISO timestamp; keep the date.
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


class Allowlist:
    """JSON-backed allowlist, fail-closed, lazily reloaded."""

    def __init__(self, path, owner_id: int) -> None:
        self.path = Path(path)
        self.owner_id = owner_id
        # Entries keyed by numeric id.
        self._entries: dict[int, dict] = {}
        # Pending entries keyed by username, without the username field.
        self._pending: dict[str, dict] = {}
        # Owner self-prefs; the owner is never an access entry.
        # - `global_memory` opts out of isolation
        # - rate, max-effort, tool cap are self-imposed test limits
        # - Defaults leave an owner uncapped and unlimited
        self._owner_prefs: dict = self._norm_owner_prefs(None)
        self._mtime: Optional[float] = None
        self._load()

    # -- normalisation ------------------------------------------------------

    @staticmethod
    def _norm_level(v) -> str:
        # Anything but `code` degrades to `chat`; corrupt never grants code.
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

    @staticmethod
    def _norm_bool(v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def _norm_rate(cls, v) -> dict:
        """Normalize rolling-window caps to day/week ints or `None`.

        - Fails soft to no caps
        """
        v = v if isinstance(v, dict) else {}
        return {"day": cls._norm_grant(v.get("day")), "week": cls._norm_grant(v.get("week"))}

    @staticmethod
    def _norm_tool_cap(v):
        """Normalize a per-user tool cap to a list or `None`.

        - `None` means the session's full default set
        """
        return [str(x) for x in v] if isinstance(v, list) else None

    @staticmethod
    def _norm_access(v) -> dict:
        """Normalize per-user access exceptions per option.

        - Levels: hidden, readonly, delegated; unknown levels dropped
        - Fails soft to an empty map
        """
        if not isinstance(v, dict):
            return {}
        out: dict = {}
        for k, lvl in v.items():
            s = str(lvl).strip().lower()
            if s in ("hidden", "readonly", "delegated"):
                out[str(k)] = s
        return out

    @staticmethod
    def _norm_friendly(rec: dict) -> Optional[str]:
        """Owner-assigned friendly name, trimmed and capped, or `None`."""
        fname = rec.get("friendly_name")
        return (str(fname).strip()[:64] or None) if fname else None

    def _norm_record(self, rec: Optional[dict]) -> dict:
        rec = rec or {}
        uname = rec.get("username")
        uname = _norm_username(str(uname)) if uname else None
        return {
            "username": uname or None,
            "level": self._norm_level(rec.get("level")),
            "expires_at": self._norm_expiry(rec.get("expires_at")),
            "token_grant": self._norm_grant(rec.get("token_grant")),
            "max_sessions": self._norm_grant(rec.get("max_sessions")),
            "rate": self._norm_rate(rec.get("rate")),
            "global_memory": self._norm_bool(rec.get("global_memory")),
            "allow_max_effort": self._norm_bool(rec.get("allow_max_effort")),
            "tool_cap": self._norm_tool_cap(rec.get("tool_cap")),
            "access": self._norm_access(rec.get("access")),
            # Friendly names are preserved through load and normalize.
            "friendly_name": self._norm_friendly(rec),
        }

    def _norm_pending(self, rec: Optional[dict]) -> dict:
        rec = rec or {}
        return {
            "level": self._norm_level(rec.get("level")),
            "expires_at": self._norm_expiry(rec.get("expires_at")),
            "token_grant": self._norm_grant(rec.get("token_grant")),
            "max_sessions": self._norm_grant(rec.get("max_sessions")),
            "rate": self._norm_rate(rec.get("rate")),
            "global_memory": self._norm_bool(rec.get("global_memory")),
            "allow_max_effort": self._norm_bool(rec.get("allow_max_effort")),
            "tool_cap": self._norm_tool_cap(rec.get("tool_cap")),
            "access": self._norm_access(rec.get("access")),
            "friendly_name": self._norm_friendly(rec),
        }

    def _norm_owner_prefs(self, rec: Optional[dict]) -> dict:
        rec = rec if isinstance(rec, dict) else {}
        # Owner self-imposed limits default to uncapped.
        # - No rate caps, max-effort allowed, no tool cap
        # - Legacy `owner_prefs` upgrades transparently on load
        ame = rec.get("allow_max_effort")
        # Owner has no entry; username and friendly name live here.
        # - Username is auto-captured on owner-only screens
        uname = rec.get("username")
        uname = _norm_username(str(uname)) if uname else None
        fname = rec.get("friendly_name")
        fname = str(fname).strip()[:64] if fname else None
        return {
            "global_memory": self._norm_bool(rec.get("global_memory")),
            "rate": self._norm_rate(rec.get("rate")),
            "allow_max_effort": True if ame is None else self._norm_bool(ame),
            "tool_cap": self._norm_tool_cap(rec.get("tool_cap")),
            "max_sessions": self._norm_grant(rec.get("max_sessions")),
            "username": uname or None,
            "friendly_name": fname or None,
        }

    # -- loading / saving ---------------------------------------------------

    def _load(self) -> None:
        """Reload state from disk; reset to owner-only on error."""
        try:
            mtime = self.path.stat().st_mtime
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            entries: dict[int, dict] = {}
            pending: dict[str, dict] = {}
            owner_prefs = self._norm_owner_prefs(None)
            if isinstance(data, dict) and ("entries" in data or "version" in data):
                owner_prefs = self._norm_owner_prefs(data.get("owner_prefs"))
                for sid, rec in (data.get("entries") or {}).items():
                    try:
                        uid = int(sid)
                    except (TypeError, ValueError):
                        continue
                    if uid == self.owner_id:
                        continue  # Owner is synthesised, never stored
                    entries[uid] = self._norm_record(rec)
                for name, rec in (data.get("pending_usernames") or {}).items():
                    n = _norm_username(str(name))
                    if n:
                        pending[n] = self._norm_pending(rec)
            else:
                # Legacy `{ids, usernames}`: migrate as code, no expiry, no cap.
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
            self._owner_prefs = owner_prefs
            self._mtime = mtime
        except Exception:
            self._entries = {}
            self._pending = {}
            self._owner_prefs = self._norm_owner_prefs(None)
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
            "owner_prefs": dict(self._owner_prefs),
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
        """The user's record by id, else pending username, or `None`."""
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
                # Date-only expiry is valid through that UTC day.
                return _utcnow().date() > date.fromisoformat(s)
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return _utcnow() > dt
        except Exception:
            # Unparseable expiry fails closed: treated as expired.
            return True

    def is_allowed(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """True if the user is owner or allowed.

        - Never allows all; safe for `None`
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return True
        rec = self._find(user_id, username)
        return rec is not None and not self._is_expired(rec)

    def level_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[str]:
        """The user's access level, or `None` if denied or expired.

        - Owner is always `code`
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return "code"
        rec = self._find(user_id, username)
        if rec is None or self._is_expired(rec):
            return None
        return self._norm_level(rec.get("level"))

    def token_grant_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[int]:
        """The user's legacy cumulative token grant; `None` is unlimited.

        - Owner is always unlimited
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return None
        rec = self._find(user_id, username)
        if rec is None:
            return None
        return self._norm_grant(rec.get("token_grant"))

    def max_sessions_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[int]:
        """Per-user session-count override; 0 means unlimited.

        - `None` inherits the global default
        - Owner reads its own self-override
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return self._norm_grant(self._owner_prefs.get("max_sessions"))
        rec = self._find(user_id, username)
        return self._norm_grant(rec.get("max_sessions")) if rec else None

    def rate_of(self, user_id: Optional[int], username: Optional[str]) -> dict:
        """The user's rolling-window token caps; `None` means no cap.

        - Owner reads its own self-imposed caps
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # Owner reads its self-imposed caps.
            return self._norm_rate(self._owner_prefs.get("rate"))
        rec = self._find(user_id, username)
        return self._norm_rate(rec.get("rate")) if rec else {"day": None, "week": None}

    def global_memory_of(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Whether sessions load global memory instead of isolating.

        - Owner reads `owner_prefs`; others default to False
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return self._norm_bool(self._owner_prefs.get("global_memory"))
        rec = self._find(user_id, username)
        return self._norm_bool(rec.get("global_memory")) if rec else False

    def allow_max_effort_of(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Whether the user may select `max` reasoning effort.

        - Owner reads its own pref, default True
        - Others default to False
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # Owner can self-revoke max effort to test the gate.
            return self._norm_bool(self._owner_prefs.get("allow_max_effort", True))
        rec = self._find(user_id, username)
        return self._norm_bool(rec.get("allow_max_effort")) if rec else False

    def tool_cap_of(self, user_id: Optional[int], username: Optional[str]):
        """Tools the user may use, or `None` if uncapped.

        - Owner reads its own self-cap, default `None`
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # Owner can self-impose a tool cap to test it.
            return self._norm_tool_cap(self._owner_prefs.get("tool_cap"))
        rec = self._find(user_id, username)
        return self._norm_tool_cap(rec.get("tool_cap")) if rec else None

    def pin(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Upgrade a username-only match to a numeric id.

        - Carries the record over; refreshes a known entry's username
        - Returns True if a new pin was made
        """
        self._reload_if_changed()
        if user_id is None or user_id == self.owner_id:
            # Owner is synthesised, never stored.
            # - Drop a legacy pending entry for the owner's username
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
        """Mutable record for an id or username target, or `None`.

        - A username also matches an entry pinned to an id
        - Keeps cards working after a mid-session pin
        """
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        if candidate.isascii() and candidate.isdigit():
            return self._entries.get(int(raw))
        name = _norm_username(raw)
        if name in self._pending:
            return self._pending[name]
        for rec in self._entries.values():
            if rec.get("username") == name:
                return rec
        return None

    def add(
        self,
        target: str,
        level: Optional[str] = None,
        expires_at: Optional[str] = None,
        token_grant: Optional[int] = None,
    ) -> tuple[str, str]:
        """Grant access to an id or username.

        - `level` defaults to `chat` (least privilege)
        - Expiry and grant apply only when provided
        - Returns `(kind, value)`; kind is id/username/invalid/owner
        """
        self._reload_if_changed()
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        lvl = self._norm_level(level) if level else "chat"
        if candidate.isascii() and candidate.isdigit():
            uid = int(raw)
            if uid == self.owner_id:
                return ("owner", str(uid))  # Always allowed; nothing to store
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
        """Change an existing entry's level; True if found."""
        self._reload_if_changed()
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["level"] = self._norm_level(level)
        self._save()
        return True

    def set_expiry(self, target: str, expires_at: Optional[str]) -> bool:
        """Set or clear an entry's expiry; True if found."""
        self._reload_if_changed()
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["expires_at"] = self._norm_expiry(expires_at)
        self._save()
        return True

    def set_friendly_name(self, target: str, name: Optional[str]) -> bool:
        """Set or clear an entry's friendly name.

        - Blank or `off` clears it; True if found
        """
        self._reload_if_changed()
        n = (name or "").strip()
        keep = bool(n) and n.lower() not in ("off", "none", "clear", "-")
        # Owner has no entry; friendly name lives in `owner_prefs`.
        if self._is_owner_target(target):
            if keep:
                self._owner_prefs["friendly_name"] = n[:64]
            else:
                self._owner_prefs["friendly_name"] = None
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        if keep:
            rec["friendly_name"] = n[:64]
        else:
            rec.pop("friendly_name", None)
        self._save()
        return True

    def note_owner_identity(self, uid: int, username: Optional[str]) -> bool:
        """Remember the owner's current `@username`.

        - Owner has no entry, so it lives in owner prefs
        - Saves only on change; returns True if saved
        """
        if uid != self.owner_id or not username:
            return False
        self._reload_if_changed()
        norm = _norm_username(str(username))
        if not norm or self._owner_prefs.get("username") == norm:
            return False
        self._owner_prefs["username"] = norm
        self._save()
        return True

    def grant_tokens(self, target: str, tokens: Optional[int]) -> bool:
        """Add tokens to a target's cumulative grant.

        - `tokens=None` means unlimited; True if found
        """
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

    def _is_owner_target(self, target: str) -> bool:
        """True if a target string resolves to the owner id."""
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        return candidate.isascii() and candidate.isdigit() and int(raw) == self.owner_id

    def set_global_memory(self, target: str, on: bool) -> bool:
        """Grant or revoke global memory for a user.

        - Owner's flag lives in `owner_prefs`
        - True if the target exists or is owner
        """
        self._reload_if_changed()
        if self._is_owner_target(target):
            self._owner_prefs["global_memory"] = bool(on)
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["global_memory"] = bool(on)
        self._save()
        return True

    def set_allow_max_effort(self, target: str, on: bool) -> bool:
        """Grant or revoke permission to select `max` effort.

        - Owner stores its own self-pref; True if found
        """
        self._reload_if_changed()
        if self._is_owner_target(target):
            # Owner stores a self-pref.
            self._owner_prefs["allow_max_effort"] = bool(on)
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["allow_max_effort"] = bool(on)
        self._save()
        return True

    def set_tool_cap(self, target: str, tools) -> bool:
        """Set or clear a user's tool cap.

        - A list limits tools; `None` means uncapped
        - Owner stores its own self-cap
        """
        self._reload_if_changed()
        if self._is_owner_target(target):
            # Owner stores a self-cap.
            self._owner_prefs["tool_cap"] = self._norm_tool_cap(tools)
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["tool_cap"] = self._norm_tool_cap(tools)
        self._save()
        return True

    def access_of(self, user_id: Optional[int], username: Optional[str]) -> dict:
        """Per-option access exceptions for a user, or empty.

        - Empty means the owner's base access applies
        - Owner has none; always full access
        """
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return {}
        rec = self._find(user_id, username)
        return self._norm_access(rec.get("access")) if rec else {}

    def set_access_exception(self, target: str, option: str, level: Optional[str]) -> bool:
        """Set or clear a per-user access exception.

        - `level`: hidden, readonly, delegated, or `None` to clear
        - Owner is always full; no-op success
        """
        self._reload_if_changed()
        if self._is_owner_target(target):
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        acc = self._norm_access(rec.get("access"))
        if level is None:
            acc.pop(option, None)
        else:
            s = str(level).strip().lower()
            if s in ("hidden", "readonly", "delegated"):
                acc[option] = s
        rec["access"] = acc
        self._save()
        return True

    def set_rate(self, target: str, day=_UNSET, week=_UNSET) -> bool:
        """Set or clear a user's rolling-window token caps.

        - `day`/`week`: int cap, `None` clears, unset keeps
        - Owner stores its own self-caps; True if found
        """
        self._reload_if_changed()
        if self._is_owner_target(target):
            # Owner can set a self-cap.
            rate = self._norm_rate(self._owner_prefs.get("rate"))
            if day is not _UNSET:
                rate["day"] = None if day is None else self._norm_grant(day)
            if week is not _UNSET:
                rate["week"] = None if week is None else self._norm_grant(week)
            self._owner_prefs["rate"] = rate
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rate = self._norm_rate(rec.get("rate"))
        if day is not _UNSET:
            rate["day"] = None if day is None else self._norm_grant(day)
        if week is not _UNSET:
            rate["week"] = None if week is None else self._norm_grant(week)
        rec["rate"] = rate
        self._save()
        return True

    def set_max_sessions(self, target: str, n) -> bool:
        """Set or clear a user's session-count cap.

        - 0 is unlimited; `None` inherits the global default
        - Owner stores its own override
        """
        self._reload_if_changed()
        val = None if n is None else self._norm_grant(n)
        if self._is_owner_target(target):
            self._owner_prefs["max_sessions"] = val
            self._save()
            return True
        rec = self._record_for_target(target)
        if rec is None:
            return False
        rec["max_sessions"] = val
        self._save()
        return True

    def remove(self, target: str) -> bool:
        """Remove a matching id or username.

        - Also drops an entry whose stored username matches
        - Returns True if anything was removed
        """
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

    def describe(self, target: str) -> Optional[dict]:
        """Owner-aware view of one target's settings for its card.

        - Returns `None` if neither owner nor known user
        - `kind`: owner, entry, or pending
        """
        self._reload_if_changed()
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        is_id = candidate.isascii() and candidate.isdigit()
        if is_id and int(raw) == self.owner_id:
            return {
                # Surface the owner's captured username and friendly name.
                "kind": "owner", "id": self.owner_id,
                "username": self._owner_prefs.get("username"),
                "level": "code", "expires_at": None, "token_grant": None,
                # Reflect the owner's self-imposed limits on the card.
                "rate": self._norm_rate(self._owner_prefs.get("rate")),
                "global_memory": self._norm_bool(self._owner_prefs.get("global_memory")),
                "allow_max_effort": self._norm_bool(self._owner_prefs.get("allow_max_effort", True)),
                "tool_cap": self._norm_tool_cap(self._owner_prefs.get("tool_cap")),
                "max_sessions": self._norm_grant(self._owner_prefs.get("max_sessions")),
                "access": {},
                "friendly_name": self._owner_prefs.get("friendly_name"),
            }
        rec = self._record_for_target(target)
        if rec is None:
            return None
        # A username target may resolve to a pinned entry.
        # - Find its id so the card shows usage stats
        rec_id = None if is_id else next(
            (uid for uid, e in self._entries.items() if e is rec), None
        )
        if is_id or rec_id is not None:
            out = self._norm_record(rec)
            out["kind"] = "entry"
            out["id"] = int(raw) if is_id else rec_id
        else:
            out = self._norm_pending(rec)
            out["kind"] = "pending"
            out["id"] = None
            out["username"] = _norm_username(raw)
        out["friendly_name"] = rec.get("friendly_name")  # Owner-assigned alias
        return out

    def snapshot(self) -> dict:
        """Stable, sorted view of the allowlist for the user list."""
        self._reload_if_changed()
        return {
            "owner_id": self.owner_id,
            "owner_prefs": dict(self._owner_prefs),
            "entries": {uid: dict(rec) for uid, rec in sorted(self._entries.items())},
            "pending": {n: dict(rec) for n, rec in sorted(self._pending.items())},
        }
