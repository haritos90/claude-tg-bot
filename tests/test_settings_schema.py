"""Unit tests for the unified settings registry + resolver (#138, PART 1).

Covers the precedence walk (SESSION → USER → GLOBAL → default), role gating, and
the critical equivalence: routing the sandbox decision through ``resolve()`` must
match the OLD inline expression ``settings.sandbox_code and not state.no_sandbox``
for EVERY combination of global flag and per-session override.
"""

from types import SimpleNamespace

import settings_schema
from settings_schema import Role, Scope


def _state(**kw):
    """A minimal stand-in for db.ThreadState (only the attrs adapters read)."""
    base = dict(
        model="claude-sonnet-4-6", effort=None, permission_mode="default",
        big_memory=False, stream_enabled=True, max_turns=None,
        no_sandbox=False, created_by=None, chat_id=1,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_sandbox_resolve_matches_old_expression():
    """resolve(sandbox) == settings.sandbox_code and not state.no_sandbox, ∀ combos."""
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
    """no_sandbox set → SESSION override; otherwise the GLOBAL flag is the source."""
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
    """model: SESSION wins; then USER default; then GLOBAL default; then built-in."""
    s = settings_schema.get("model")
    settings = SimpleNamespace(default_model="claude-opus-4-8")

    # SESSION present → SESSION wins.
    ctx = settings_schema.make_ctx(
        state=_state(model="claude-haiku-4-5"), settings=settings,
        user_defaults={"model": "claude-sonnet-4-6"},
    )
    assert settings_schema.resolve(s, ctx) == ("claude-haiku-4-5", Scope.SESSION)

    # No SESSION value → USER default wins.
    ctx = settings_schema.make_ctx(
        state=_state(model=None), settings=settings,
        user_defaults={"model": "claude-sonnet-4-6"},
    )
    assert settings_schema.resolve(s, ctx) == ("claude-sonnet-4-6", Scope.USER)

    # No SESSION/USER → GLOBAL default_model.
    ctx = settings_schema.make_ctx(state=_state(model=None), settings=settings)
    assert settings_schema.resolve(s, ctx) == ("claude-opus-4-8", Scope.GLOBAL)


def test_resolve_falls_back_to_builtin_default():
    """effort has no GLOBAL adapter; empty ctx → built-in default (None)."""
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
    # Owner-only: hidden + uneditable for everyone below OWNER.
    assert sandbox.can_view(Role.OWNER) and sandbox.can_edit(Role.OWNER)
    assert not sandbox.can_view(Role.CODE)
    assert not sandbox.can_edit(Role.CODE)
    # model is editable by any CHAT+ user.
    model = settings_schema.get("model")
    assert model.can_edit(Role.CHAT) and model.can_view(Role.CHAT)
    assert not model.can_edit(Role.GUEST)


def test_memory_bool_user_coercion():
    """A stored user-default of 0/1 coerces to a real bool in the USER getter."""
    s = settings_schema.get("memory")
    # big_memory=None so the SESSION tier has no opinion and we fall to USER.
    ctx = settings_schema.make_ctx(
        state=_state(big_memory=None), user_defaults={"memory": 1}
    )
    value, scope = settings_schema.resolve(s, ctx)
    assert value is True and scope is Scope.USER
