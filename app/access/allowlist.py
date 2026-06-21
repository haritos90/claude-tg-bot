"""A small, dependency-free allowlist backed by a JSON file.

Access is granted when the user is the owner, or when their numeric id (or, until
pinned, their ``@username``) has an allowlist **entry** that has not expired.
Numeric ids are authoritative; usernames are a convenience that is upgraded to an
id on first contact (``pin``).

Each entry carries per-user access metadata (#102/#103/#105 + the per-user
controls #120/global-memory/max-effort):

- ``level``         — ``"chat"`` (chat sessions only) or ``"code"`` (chat + code).
- ``expires_at``    — an ISO date (``YYYY-MM-DD``) / datetime, or ``None`` for never.
- ``token_grant``   — a legacy cumulative token allowance (``None`` = unlimited).
  Kept for backward compatibility but NO LONGER enforced — superseded by ``rate``
  (#120 replaced the lifetime cap with rolling windows).
- ``rate``          — rolling-window token caps ``{"day": <int|null>, "week":
  <int|null>}`` (``None`` = no cap for that window). Enforced from the trailing
  5h / 7d of ``db.usage`` (no reset job — computed from timestamps).
- ``global_memory`` — when ``True``, that user's sessions load ``setting_sources=
  ["user"]`` (the owner's ``~/.claude`` settings + ``CLAUDE.md`` / memory) instead
  of ``[]``. This DELIBERATELY relaxes the per-session isolation invariant for the
  user, so it is owner-granted and OFF by default (see ``engine``).
- ``allow_max_effort`` — when ``True``, the user may select the ``max`` reasoning
  effort (expensive on the shared subscription); OFF by default, owner-granted.

The OWNER is synthesised in memory (never an access entry), so the owner's only
build-affecting preference — ``global_memory`` — lives in a separate top-level
``owner_prefs`` map; the owner is always ``code`` / unexpiring / uncapped /
max-effort-allowed.

On-disk JSON (version 2)::

    {
      "version": 2,
      "owner_prefs": {"global_memory": <bool>},
      "entries": {"<id>": {"username": <str|null>, "level": "chat|code",
                            "expires_at": <str|null>, "token_grant": <int|null>,
                            "rate": {"day": <int|null>, "week": <int|null>},
                            "global_memory": <bool>, "allow_max_effort": <bool>}},
      "pending_usernames": {"<name>": {"level": ..., "expires_at": ...,
                                       "token_grant": ..., "rate": ...,
                                       "global_memory": ..., "allow_max_effort": ...}}
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

# Sentinel for "leave this field unchanged" in set_rate (so a caller can update
# only the day OR only the week cap without clobbering the other).
_UNSET = object()


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
        # id   -> {username, level, expires_at, token_grant, rate, global_memory, allow_max_effort}
        self._entries: dict[int, dict] = {}
        # name -> same minus username (carried once the user is pinned to an id)
        self._pending: dict[str, dict] = {}
        # Owner self-prefs (the owner is never an access entry). global_memory is a
        # build-affecting opt-out of isolation; rate / allow_max_effort / tool_cap are
        # SELF-imposed limits the owner can set on itself to test the per-user caps
        # (#185) — all default to uncapped/allowed so an owner who set nothing stays
        # unlimited. The owner is always code / unexpiring regardless.
        # was: {"global_memory": False} — extended for #185 (owner self-limit prefs)
        self._owner_prefs: dict = self._norm_owner_prefs(None)
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

    @staticmethod
    def _norm_bool(v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def _norm_rate(cls, v) -> dict:
        """Normalize a rolling-window cap dict to ``{"day": int|None, "week":
        int|None}`` (None = no cap for that window). Fail-soft to no caps."""
        v = v if isinstance(v, dict) else {}
        return {"day": cls._norm_grant(v.get("day")), "week": cls._norm_grant(v.get("week"))}

    @staticmethod
    def _norm_tool_cap(v):
        """Normalize a per-user tool cap to a ``list[str]`` (the tools the user MAY
        use) or ``None`` (no cap = the session's full default set). #131."""
        return [str(x) for x in v] if isinstance(v, list) else None

    @staticmethod
    def _norm_access(v) -> dict:
        """Normalize a per-user ACCESS-exceptions map {option: 'hidden'|'readonly'|
        'delegated'} (#151, menu.md §4.1). Drops unknown levels; fail-soft to {}."""
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
        """#284: the owner-assigned friendly name, trimmed/capped (None if unset)."""
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
            # #284: was DROPPED here — so any reload from disk wiped friendly names set
            # via /users; now preserved through the load/normalize path.
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
            "friendly_name": self._norm_friendly(rec),  # #284: was dropped on reload
        }

    def _norm_owner_prefs(self, rec: Optional[dict]) -> dict:
        rec = rec if isinstance(rec, dict) else {}
        # #185: rate / allow_max_effort / tool_cap are the owner's SELF-imposed limits
        # (for testing the per-user caps). Defaults keep an owner who set nothing fully
        # uncapped: no rate caps, max-effort allowed, no tool cap. A missing/legacy
        # owner_prefs (only global_memory) upgrades transparently on load.
        ame = rec.get("allow_max_effort")
        # #272: the owner has no access ENTRY, so their @username / owner-assigned
        # friendly name (used to label the owner on /users, the stats table, and the
        # owner card) live here. username is auto-captured on owner-only screens.
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
        """(Re)load state from disk. On any error, reset to empty (owner-only)."""
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

    def max_sessions_of(self, user_id: Optional[int], username: Optional[str]) -> Optional[int]:
        """The user's per-user session-count override (int; 0 = unlimited), or ``None``
        = inherit the global default. The owner reads its OWN self-override (#185),
        also ``None`` by default (so the owner inherits the global / is uncapped per the
        caller's resolution)."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return self._norm_grant(self._owner_prefs.get("max_sessions"))
        rec = self._find(user_id, username)
        return self._norm_grant(rec.get("max_sessions")) if rec else None

    def rate_of(self, user_id: Optional[int], username: Optional[str]) -> dict:
        """The user's rolling-window token caps ``{"day": int|None, "week":
        int|None}`` (None = no cap). Owner reads its OWN self-caps (#185), default
        uncapped (#120)."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # #185: owner reads its self-imposed caps. was: return {"day": None, "week": None}
            return self._norm_rate(self._owner_prefs.get("rate"))
        rec = self._find(user_id, username)
        return self._norm_rate(rec.get("rate")) if rec else {"day": None, "week": None}

    def global_memory_of(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Whether this user's sessions load the global (``~/.claude``) memory
        instead of running fully isolated. Owner reads its own ``owner_prefs``;
        everyone else defaults to False (isolated)."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return self._norm_bool(self._owner_prefs.get("global_memory"))
        rec = self._find(user_id, username)
        return self._norm_bool(rec.get("global_memory")) if rec else False

    def allow_max_effort_of(self, user_id: Optional[int], username: Optional[str]) -> bool:
        """Whether this user may select the (expensive) ``max`` reasoning effort.
        Owner reads its OWN self-pref (default True — #185); everyone else defaults to
        False (#120/effort gate)."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # #185: owner can self-revoke max-effort to test the gate. was: return True
            return self._norm_bool(self._owner_prefs.get("allow_max_effort", True))
        rec = self._find(user_id, username)
        return self._norm_bool(rec.get("allow_max_effort")) if rec else False

    def tool_cap_of(self, user_id: Optional[int], username: Optional[str]):
        """The tools this user MAY use (a ``list[str]``), or ``None`` = uncapped (the
        session's full default set). Owner reads its OWN self-cap (default None — #185)."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            # #185: owner can self-impose a tool cap to test it. was: return None
            return self._norm_tool_cap(self._owner_prefs.get("tool_cap"))
        rec = self._find(user_id, username)
        return self._norm_tool_cap(rec.get("tool_cap")) if rec else None

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
        """The mutable record for an id-or-username target, or None if absent. A
        username resolves to its pending record OR — if the user was already pinned
        to an id — the entry whose stored username matches, so a card/command opened
        on a pending user keeps working after they're pinned mid-session (#121 audit;
        same username->entry fallback `remove()` already uses)."""
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

    def set_friendly_name(self, target: str, name: Optional[str]) -> bool:
        """Set/clear an entry's owner-assigned friendly name (#171). A blank/`off`
        name clears it. Returns True if the target exists."""
        self._reload_if_changed()
        n = (name or "").strip()
        keep = bool(n) and n.lower() not in ("off", "none", "clear", "-")
        # #272: the owner has no entry — their friendly name lives in owner_prefs.
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
        """#272: remember the owner's current @username (the owner is synthesised, never
        an access entry, so there's nowhere else to learn it). Cheap no-op when unchanged;
        only persists on an actual change. Returns True if something was saved."""
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

    def _is_owner_target(self, target: str) -> bool:
        """True iff a mutation target string resolves to the owner's numeric id."""
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        return candidate.isascii() and candidate.isdigit() and int(raw) == self.owner_id

    def set_global_memory(self, target: str, on: bool) -> bool:
        """Grant/revoke GLOBAL MEMORY for a user. The owner's flag lives in
        ``owner_prefs`` (the owner is never an access entry). Returns True if the
        target exists (or is the owner)."""
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
        """Grant/revoke permission to select the ``max`` effort level. The owner stores
        its OWN self-pref (#185). Returns True if the target exists (or is the owner)."""
        self._reload_if_changed()
        if self._is_owner_target(target):
            # #185: owner self-pref. was: return True  # owner is always allowed
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
        """Set/clear a user's TOOL CAP (#131): ``tools`` is a list (the only tools
        the user may use) or None (uncapped). The owner stores its OWN self-cap
        (#185). Returns True if the target exists (or is the owner)."""
        self._reload_if_changed()
        if self._is_owner_target(target):
            # #185: owner self-cap. was: return True  # owner always uncapped
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
        """The user's per-option ACCESS EXCEPTIONS {option: 'hidden'|'readonly'|
        'delegated'} (#151), or {} (use the owner's base access). The owner has no
        exceptions — they always have full access."""
        self._reload_if_changed()
        if user_id is not None and user_id == self.owner_id:
            return {}
        rec = self._find(user_id, username)
        return self._norm_access(rec.get("access")) if rec else {}

    def set_access_exception(self, target: str, option: str, level: Optional[str]) -> bool:
        """Set (or clear, ``level=None``) a per-user access EXCEPTION for one option
        (#151). ``level`` is 'hidden' / 'readonly' / 'delegated'. The owner is always
        full (no-op success). Returns True if the target exists."""
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
        """Set/clear a user's rolling-window caps (#120). Pass ``day``/``week`` as an
        int (cap, in tokens), None (clear that window), or leave unset to keep it.
        The owner stores its OWN self-caps (#185). Returns True if the target exists
        (or is the owner)."""
        self._reload_if_changed()
        if self._is_owner_target(target):
            # #185: owner self-cap (was a no-op: "owner is never rate-limited").
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
        """Set/clear a user's session-count cap. ``n`` = int (0 = unlimited) or ``None``
        to clear (inherit the global default). The owner stores its OWN override (#185).
        Returns True if the target exists (or is the owner)."""
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

    def describe(self, target: str) -> Optional[dict]:
        """A normalized, owner-aware view of ONE target's settings (feeds the
        per-user card). Returns None when the target is neither the owner nor a
        known entry/pending user. ``kind`` is ``"owner"``/``"entry"``/``"pending"``."""
        self._reload_if_changed()
        raw = target.strip()
        candidate = raw[1:] if raw.startswith("-") else raw
        is_id = candidate.isascii() and candidate.isdigit()
        if is_id and int(raw) == self.owner_id:
            return {
                # #272: surface the owner's captured username + owner-set friendly name
                # (were both hardcoded None, so the owner showed only as a bare id).
                "kind": "owner", "id": self.owner_id,
                "username": self._owner_prefs.get("username"),
                "level": "code", "expires_at": None, "token_grant": None,
                # #185: reflect the owner's self-imposed limits on the card (were
                # hardcoded uncapped: rate {None,None} / allow_max_effort True / tool_cap None).
                "rate": self._norm_rate(self._owner_prefs.get("rate")),
                "global_memory": self._norm_bool(self._owner_prefs.get("global_memory")),
                "allow_max_effort": self._norm_bool(self._owner_prefs.get("allow_max_effort", True)),
                "tool_cap": self._norm_tool_cap(self._owner_prefs.get("tool_cap")),
                "max_sessions": self._norm_grant(self._owner_prefs.get("max_sessions")),
                "access": {},
                "friendly_name": self._owner_prefs.get("friendly_name"),  # #272
            }
        rec = self._record_for_target(target)
        if rec is None:
            return None
        # A username target may resolve to a pinned ENTRY (see _record_for_target's
        # username->entry fallback); find its id so the card shows entry + usage
        # stats, not "(unpinned)" with id=None (#121 audit).
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
        out["friendly_name"] = rec.get("friendly_name")  # owner-assigned alias (#171)
        return out

    def snapshot(self) -> dict:
        """A stable, sorted view of the current allowlist (feeds ``/users``)."""
        self._reload_if_changed()
        return {
            "owner_id": self.owner_id,
            "owner_prefs": dict(self._owner_prefs),
            "entries": {uid: dict(rec) for uid, rec in sorted(self._entries.items())},
            "pending": {n: dict(rec) for n, rec in sorted(self._pending.items())},
        }
