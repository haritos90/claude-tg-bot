"""Unit tests for the unified settings registry and resolver.

- precedence walk: SESSION, USER, GLOBAL, default
- role gating
- `resolve()` equals `sandbox_code and not no_sandbox` for all combos
"""

from types import SimpleNamespace

from app.access import settings_schema
from app.access.settings_schema import Role, Scope


def _state(**kw):
    """Minimal stand-in for db.ThreadState (attrs adapters read)."""
    base = dict(
        model="claude-sonnet-4-6", effort=None, permission_mode="default",
        big_memory=False, stream_enabled=True, max_turns=None,
        no_sandbox=False, created_by=None, chat_id=1,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_sandbox_resolve_matches_old_expression():
    """`resolve(sandbox)` equals `sandbox_code and not no_sandbox`, all combos."""
    for global_on in (True, False):
        for no_sandbox in (True, False):
            settings = SimpleNamespace(sandbox_code=global_on)
            state = _state(no_sandbox=no_sandbox)
            ctx = settings_schema.make_ctx(state=state, settings=settings)
            value, _scope = settings_schema.resolve(
                settings_schema.get("sandbox"), ctx
            )
            expected = bool(global_on and not no_sandbox)
            assert bool(value) is expected, (global_on, no_sandbox)


def test_sandbox_source_scope():
    """`no_sandbox` set means SESSION override; else GLOBAL flag."""
    settings = SimpleNamespace(sandbox_code=True)
    _v, scope = settings_schema.resolve(
        settings_schema.get("sandbox"),
        settings_schema.make_ctx(state=_state(no_sandbox=True), settings=settings),
    )
    assert scope is Scope.SESSION
    _v, scope = settings_schema.resolve(
        settings_schema.get("sandbox"),
        settings_schema.make_ctx(state=_state(no_sandbox=False), settings=settings),
    )
    assert scope is Scope.GLOBAL


def test_precedence_session_over_user_over_global():
    """model: SESSION wins, then USER, GLOBAL, built-in default."""
    s = settings_schema.get("model")
    settings = SimpleNamespace(default_model="claude-opus-4-8")

    # SESSION present: SESSION wins.
    ctx = settings_schema.make_ctx(
        state=_state(model="claude-haiku-4-5"), settings=settings,
        user_defaults={"model": "claude-sonnet-4-6"},
    )
    assert settings_schema.resolve(s, ctx) == ("claude-haiku-4-5", Scope.SESSION)

    # No SESSION value: USER default wins.
    ctx = settings_schema.make_ctx(
        state=_state(model=None), settings=settings,
        user_defaults={"model": "claude-sonnet-4-6"},
    )
    assert settings_schema.resolve(s, ctx) == ("claude-sonnet-4-6", Scope.USER)

    # No SESSION/USER: GLOBAL `default_model`.
    ctx = settings_schema.make_ctx(state=_state(model=None), settings=settings)
    assert settings_schema.resolve(s, ctx) == ("claude-opus-4-8", Scope.GLOBAL)


def test_resolve_falls_back_to_builtin_default():
    """effort has no GLOBAL adapter; empty ctx gives None default."""
    s = settings_schema.get("effort")
    ctx = settings_schema.make_ctx(state=_state(effort=None))
    value, scope = settings_schema.resolve(s, ctx)
    assert value is None and scope is Scope.GLOBAL


def test_user_scope_for_effort():
    s = settings_schema.get("effort")
    ctx = settings_schema.make_ctx(
        state=_state(effort=None), user_defaults={"effort": "high"}
    )
    assert settings_schema.resolve(s, ctx) == ("high", Scope.USER)


def test_role_ordering_and_gates():
    assert Role.GUEST < Role.CHAT < Role.CODE < Role.OWNER
    sandbox = settings_schema.get("sandbox")
    # Owner-only: hidden and uneditable below OWNER.
    assert sandbox.can_view(Role.OWNER) and sandbox.can_edit(Role.OWNER)
    assert not sandbox.can_view(Role.CODE)
    assert not sandbox.can_edit(Role.CODE)
    # model is editable by any CHAT+ user.
    model = settings_schema.get("model")
    assert model.can_edit(Role.CHAT) and model.can_view(Role.CHAT)
    assert not model.can_edit(Role.GUEST)


def test_bool_user_coercion():
    """A stored user-default of 0/1 coerces to a real bool.

    - auto_compact has the same USER-scope bool shape
    """
    s = settings_schema.get("auto_compact")
    ctx = settings_schema.make_ctx(state=_state(), user_defaults={"auto_compact": 0})
    value, scope = settings_schema.resolve(s, ctx)
    assert value is False and scope is Scope.USER


def test_retired_1m_toggle_is_gone():
    """The 1M-context toggle is retired: no setting, no access row."""
    assert "memory" not in settings_schema.SETTINGS
    assert "memory" not in settings_schema.BASE_ACCESS_DEFAULTS


# ---- Access model ----
from app.access.settings_schema import Access  # noqa: E402


def test_base_access_defaults_match_table_23():
    """Built-in base access matches the menu.md access table.

    - sandbox and auto-compact Hidden
    - usage Read-only, the rest Delegated
    """
    d = settings_schema.BASE_ACCESS_DEFAULTS
    assert d["model"] is Access.DELEGATED
    assert d["auto_compact"] is Access.HIDDEN
    assert d["sandbox"] is Access.HIDDEN
    assert d["usage_display"] is Access.READONLY


def test_effective_access_owner_always_delegated():
    """The owner always has full access, even to Hidden options."""
    hidden = settings_schema.get("auto_compact")  # default HIDDEN
    assert settings_schema.effective_access(hidden, settings_schema.make_ctx(role=Role.OWNER)) is Access.DELEGATED


def test_effective_access_precedence_exception_over_base_over_default():
    """Precedence: exception, then owner base override, then built-in default."""
    s = settings_schema.get("model")  # default DELEGATED
    # base override: READ-ONLY.
    ctx = settings_schema.make_ctx(role=Role.CHAT, access_base={"model": "readonly"})
    assert settings_schema.effective_access(s, ctx) is Access.READONLY
    # A per-user exception beats the base override.
    ctx = settings_schema.make_ctx(role=Role.CHAT, access_base={"model": "readonly"},
                                   access_exceptions={"model": "delegated"})
    assert settings_schema.effective_access(s, ctx) is Access.DELEGATED
    # Nothing configured: built-in default.
    ctx = settings_schema.make_ctx(role=Role.CHAT)
    assert settings_schema.effective_access(s, ctx) is Access.DELEGATED


def test_can_view_edit_combine_role_and_access():
    """Visibility and editability follow role gate and access.

    - visible iff role-gate and access not HIDDEN
    - editable iff role-gate and DELEGATED
    """
    model = settings_schema.get("model")
    ctx = settings_schema.make_ctx(role=Role.CHAT)               # default DELEGATED
    assert settings_schema.can_view_setting(model, ctx)
    assert settings_schema.can_edit_setting(model, ctx)
    ctx = settings_schema.make_ctx(role=Role.CHAT, access_base={"model": "readonly"})
    assert settings_schema.can_view_setting(model, ctx)
    assert not settings_schema.can_edit_setting(model, ctx)
    ctx = settings_schema.make_ctx(role=Role.CHAT, access_base={"model": "hidden"})
    assert not settings_schema.can_view_setting(model, ctx)
    assert not settings_schema.can_edit_setting(model, ctx)


def test_hidden_by_default_until_delegated():
    """Hidden-by-default options are invisible to non-owners until delegated."""
    opt = settings_schema.get("auto_compact")
    ctx = settings_schema.make_ctx(role=Role.CHAT, state=_state())
    assert not settings_schema.can_view_setting(opt, ctx)
    ctx = settings_schema.make_ctx(role=Role.CHAT, state=_state(),
                                   access_exceptions={"auto_compact": "delegated"})
    assert settings_schema.can_view_setting(opt, ctx)
    assert settings_schema.can_edit_setting(opt, ctx)


def test_resolve_effective_soft_revoke():
    """Soft revoke: when not Delegated, effective value is GLOBAL.

    - user's stored override is ignored but kept
    """
    s = settings_schema.get("model")
    settings = SimpleNamespace(default_model="claude-opus-4-8")
    # Read-only: session override ignored, value falls back to global.
    ctx = settings_schema.make_ctx(role=Role.CHAT, state=_state(model="claude-haiku-4-5"),
                                   settings=settings, access_base={"model": "readonly"})
    assert settings_schema.resolve_effective(s, ctx) == ("claude-opus-4-8", Scope.GLOBAL)
    # Delegated (default): the session override counts.
    ctx = settings_schema.make_ctx(role=Role.CHAT, state=_state(model="claude-haiku-4-5"),
                                   settings=settings)
    assert settings_schema.resolve_effective(s, ctx) == ("claude-haiku-4-5", Scope.SESSION)
