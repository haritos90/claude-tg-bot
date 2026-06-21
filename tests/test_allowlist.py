"""Tests for the per-entry allowlist model (#102/#103/#105).

The overriding invariant is **fail-closed**: a missing/corrupt file, a corrupt
record, or an unparseable expiry must NEVER widen access. The owner is always
allowed, always ``code``, always uncapped, and never written to the file.
"""

import json
from datetime import date, timedelta

from app.access import allowlist as al

OWNER = 999


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_missing_file_owner_only(tmp_path):
    a = al.Allowlist(tmp_path / "none.json", OWNER)
    assert a.is_allowed(OWNER, None) is True
    assert a.is_allowed(123, "bob") is False


def test_corrupt_file_fails_closed(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("{not json", encoding="utf-8")
    a = al.Allowlist(p, OWNER)
    assert a.is_allowed(OWNER, None) is True
    assert a.is_allowed(5, None) is False


def test_legacy_migration_grants_code(tmp_path):
    p = tmp_path / "a.json"
    _write(p, {"ids": [111], "usernames": ["Alice"]})
    a = al.Allowlist(p, OWNER)
    assert a.is_allowed(111, None) is True
    assert a.level_of(111, None) == "code"            # legacy preserved as code
    assert a.is_allowed(None, "alice") is True         # username, case-insensitive
    assert a.level_of(None, "alice") == "code"
    assert a.is_allowed(222, None) is False


def test_owner_never_stored_and_always_code(tmp_path):
    p = tmp_path / "a.json"
    _write(p, {"ids": [OWNER, 111], "usernames": []})
    a = al.Allowlist(p, OWNER)
    snap = a.snapshot()
    assert OWNER not in snap["entries"]                # synthesised, not stored
    assert a.level_of(OWNER, None) == "code"
    assert a.token_grant_of(OWNER, None) is None       # uncapped


def test_owner_identity_captured_and_friendly_name(tmp_path):
    """#272: the owner has no access entry, so their @username (auto-captured) and
    owner-assigned friendly name live in owner_prefs and surface via describe()."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    # Initially unknown → describe shows no username/friendly name.
    d0 = a.describe(str(OWNER))
    assert d0["kind"] == "owner" and d0["username"] is None and d0["friendly_name"] is None
    # Capture username (idempotent: a second identical call is a no-op).
    assert a.note_owner_identity(OWNER, "@AlexK") is True
    assert a.note_owner_identity(OWNER, "alexk") is False        # unchanged after norm
    assert a.note_owner_identity(123, "someone") is False        # non-owner ignored
    # The owner can set their OWN friendly name (no entry needed).
    assert a.set_friendly_name(str(OWNER), "Alex") is True
    d = a.describe(str(OWNER))
    assert d["username"] == "alexk" and d["friendly_name"] == "Alex"
    # Persisted: a fresh instance reading the same file keeps both.
    b = al.Allowlist(p, OWNER)
    db = b.describe(str(OWNER))
    assert db["username"] == "alexk" and db["friendly_name"] == "Alex"
    # Clearing the friendly name leaves the username intact.
    assert b.set_friendly_name(str(OWNER), "off") is True
    assert b.describe(str(OWNER))["friendly_name"] is None
    assert b.describe(str(OWNER))["username"] == "alexk"


def test_friendly_name_survives_reload_and_other_assignments(tmp_path):
    """#284 regression: a friendly name set on one user must NOT vanish when another is
    set or when the allowlist reloads from disk (it was dropped by _norm_record/_pending)."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    a.add("111", "chat")
    a.add("222", "chat")
    a.add("ghost", "chat")          # pending (username, not yet pinned to an id)
    assert a.set_friendly_name("111", "Alice") is True
    assert a.set_friendly_name("222", "Bob") is True          # setting Bob must not wipe Alice
    assert a.set_friendly_name("ghost", "Ghosty") is True
    assert a.describe("111")["friendly_name"] == "Alice"
    assert a.describe("222")["friendly_name"] == "Bob"
    # A FRESH instance (simulates a reload / restart) must keep all three.
    b = al.Allowlist(p, OWNER)
    assert b.describe("111")["friendly_name"] == "Alice"
    assert b.describe("222")["friendly_name"] == "Bob"
    assert b.describe("ghost")["friendly_name"] == "Ghosty"
    # And the snapshot the /users list reads from carries them too.
    snap = b.snapshot()
    assert snap["entries"][111]["friendly_name"] == "Alice"
    assert snap["entries"][222]["friendly_name"] == "Bob"


def test_add_level_default_chat(tmp_path):
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    kind, _ = a.add("111")
    assert kind == "id"
    assert a.level_of(111, None) == "chat"             # least privilege by default
    a.add("111", level="code")
    assert a.level_of(111, None) == "code"


def test_add_username_and_pin_carries_record(tmp_path):
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    a.add("@bobby", level="code", expires_at="2999-01-01")
    assert a.is_allowed(None, "bobby") is True
    assert a.pin(555, "bobby") is True                  # username → id
    assert a.is_allowed(555, None) is True
    assert a.level_of(555, None) == "code"             # level carried across pin
    snap = a.snapshot()
    assert "bobby" not in snap["pending"]               # moved out of pending
    assert snap["entries"][555]["username"] == "bobby"


def test_expiry_past_denied_future_allowed(tmp_path):
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    past = (date.today() - timedelta(days=2)).isoformat()
    future = (date.today() + timedelta(days=2)).isoformat()
    a.add("111", level="code", expires_at=past)
    a.add("222", level="code", expires_at=future)
    assert a.is_allowed(111, None) is False            # expired → denied
    assert a.level_of(111, None) is None
    assert a.is_allowed(222, None) is True


def test_unparseable_expiry_fails_closed(tmp_path):
    p = tmp_path / "a.json"
    _write(p, {"version": 2, "entries": {"111": {"level": "code", "expires_at": "soon"}}})
    a = al.Allowlist(p, OWNER)
    assert a.is_allowed(111, None) is False            # bad expiry → denied


def test_corrupt_level_degrades_to_chat(tmp_path):
    p = tmp_path / "a.json"
    _write(p, {"version": 2, "entries": {"111": {"level": "superuser"}}})
    a = al.Allowlist(p, OWNER)
    assert a.is_allowed(111, None) is True
    assert a.level_of(111, None) == "chat"             # unknown level → least privilege


def test_grant_tokens_add_and_unlimited(tmp_path):
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    a.add("111", level="code")
    assert a.token_grant_of(111, None) is None         # unset = unlimited
    a.grant_tokens("111", 1000)
    assert a.token_grant_of(111, None) == 1000
    a.grant_tokens("111", 500)
    assert a.token_grant_of(111, None) == 1500         # cumulative
    a.grant_tokens("111", None)
    assert a.token_grant_of(111, None) is None         # off = unlimited


def test_remove_by_id_and_username(tmp_path):
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    a.add("111", level="code")
    assert a.remove("111") is True
    assert a.is_allowed(111, None) is False
    a.add("@bobby")
    a.pin(556, "bobby")
    assert a.remove("@bobby") is True                   # deny by username after pin
    assert a.is_allowed(556, None) is False


def test_v2_roundtrip_persist(tmp_path):
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    a.add("111", level="code", expires_at="2999-12-31")
    a.grant_tokens("111", 2000)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["entries"]["111"]["level"] == "code"
    b = al.Allowlist(p, OWNER)                          # fresh instance reloads it
    assert b.level_of(111, None) == "code"
    assert b.token_grant_of(111, None) == 2000


def test_normalize_date():
    assert al.normalize_date("2026-07-01") == "2026-07-01"
    assert al.normalize_date("never") is None
    assert al.normalize_date("garbage") is None
    assert al.normalize_date("2026-07-01T12:00:00") == "2026-07-01"


# --- per-user ACCESS exceptions (#151, menu.md §4) ------------------------- #

def test_access_exception_set_get_clear(tmp_path):
    """An owner can set/clear a per-user, per-option access exception; the owner
    themselves always has none (full access)."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    a.add("123", level="code")
    assert a.access_of(123, None) == {}                       # none by default
    assert a.set_access_exception("123", "memory", "delegated") is True
    assert a.access_of(123, None) == {"memory": "delegated"}
    # a second option, and an invalid level is ignored.
    a.set_access_exception("123", "model", "readonly")
    a.set_access_exception("123", "effort", "bogus")
    got = a.access_of(123, None)
    assert got == {"memory": "delegated", "model": "readonly"}
    # clearing one removes just it; survives a reload from disk.
    assert a.set_access_exception("123", "memory", None) is True
    a2 = al.Allowlist(p, OWNER)
    assert a2.access_of(123, None) == {"model": "readonly"}
    # owner has no exceptions; setting on a missing target fails.
    assert a.access_of(OWNER, None) == {}
    assert a.set_access_exception("404", "model", "hidden") is False


def test_access_exception_persisted_in_describe(tmp_path):
    """describe() surfaces the access map (feeds the per-user card)."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    a.add("55", level="chat")
    a.set_access_exception("55", "sandbox", "delegated")
    d = a.describe("55")
    assert d is not None and d["access"] == {"sandbox": "delegated"}


# --- owner SELF-imposed limits (#185, for testing the per-user caps) ------- #

def test_owner_self_limits_default_uncapped(tmp_path):
    """A fresh owner (no prefs) stays fully uncapped/allowed — the self-limits
    only bite once explicitly set."""
    a = al.Allowlist(tmp_path / "a.json", OWNER)
    assert a.rate_of(OWNER, None) == {"day": None, "week": None}
    assert a.allow_max_effort_of(OWNER, None) is True
    assert a.tool_cap_of(OWNER, None) is None
    d = a.describe(str(OWNER))
    assert d["kind"] == "owner"
    assert d["rate"] == {"day": None, "week": None}
    assert d["allow_max_effort"] is True and d["tool_cap"] is None


def test_owner_self_rate_cap_set_get_clear_persist(tmp_path):
    """The owner can self-impose rolling-window token caps (so they fire on the
    owner's OWN turns via _access_block); they persist and clear."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    assert a.set_rate(str(OWNER), day=500_000) is True
    assert a.rate_of(OWNER, None) == {"day": 500_000, "week": None}
    assert OWNER not in a.snapshot()["entries"]          # stored in owner_prefs, not an entry
    b = al.Allowlist(p, OWNER)                            # survives a reload
    assert b.rate_of(OWNER, None) == {"day": 500_000, "week": None}
    assert b.set_rate(str(OWNER), day=None, week=None) is True   # clear → uncapped again
    assert b.rate_of(OWNER, None) == {"day": None, "week": None}


def test_owner_self_max_effort_revoke_persist(tmp_path):
    """The owner can self-revoke max-effort (to test the effort gate) and re-grant
    it; the choice persists across a reload."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    assert a.set_allow_max_effort(str(OWNER), False) is True
    assert a.allow_max_effort_of(OWNER, None) is False
    assert al.Allowlist(p, OWNER).allow_max_effort_of(OWNER, None) is False
    assert a.set_allow_max_effort(str(OWNER), True) is True
    assert a.allow_max_effort_of(OWNER, None) is True


def test_owner_self_tool_cap_set_get_clear_persist(tmp_path):
    """The owner can self-impose a tool cap and clear it; describe reflects it."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    assert a.set_tool_cap(str(OWNER), ["Read", "Grep"]) is True
    assert a.tool_cap_of(OWNER, None) == ["Read", "Grep"]
    assert a.describe(str(OWNER))["tool_cap"] == ["Read", "Grep"]
    b = al.Allowlist(p, OWNER)
    assert b.tool_cap_of(OWNER, None) == ["Read", "Grep"]
    assert b.set_tool_cap(str(OWNER), None) is True       # clear → uncapped
    assert b.tool_cap_of(OWNER, None) is None


def test_owner_prefs_legacy_upgrade(tmp_path):
    """A legacy owner_prefs carrying only global_memory upgrades transparently: the
    new self-limit keys default to uncapped/allowed, global_memory is preserved."""
    p = tmp_path / "a.json"
    _write(p, {"version": 2, "owner_prefs": {"global_memory": True}, "entries": {}})
    a = al.Allowlist(p, OWNER)
    assert a.global_memory_of(OWNER, None) is True        # preserved
    assert a.rate_of(OWNER, None) == {"day": None, "week": None}
    assert a.allow_max_effort_of(OWNER, None) is True
    assert a.tool_cap_of(OWNER, None) is None
    assert a.describe(str(OWNER))["access"] == {}


def test_max_sessions_per_user_and_owner(tmp_path):
    """Per-user session cap (#session-limit): unset → inherit (None); a positive int =
    cap; 0 = explicit unlimited; None clears. Owner stores its OWN override (#185).
    Persists across reload."""
    p = tmp_path / "a.json"
    a = al.Allowlist(p, OWNER)
    a.add("111", level="code")
    assert a.max_sessions_of(111, None) is None        # unset → inherit the global default
    assert a.max_sessions_of(OWNER, None) is None
    assert a.set_max_sessions("111", 3) is True
    assert a.max_sessions_of(111, None) == 3
    a.set_max_sessions("111", 0)                        # explicit unlimited
    assert a.max_sessions_of(111, None) == 0
    a.set_max_sessions("111", None)                     # clear → inherit
    assert a.max_sessions_of(111, None) is None
    assert a.set_max_sessions(str(OWNER), 5) is True    # owner self-override (#185)
    assert a.max_sessions_of(OWNER, None) == 5
    b = al.Allowlist(p, OWNER)                           # persists across reload
    assert b.max_sessions_of(OWNER, None) == 5
