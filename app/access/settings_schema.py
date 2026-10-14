"""Unified settings registry and scope resolver.

- Scopes resolve SESSION, then USER, then GLOBAL
- Per-scope adapters wrap existing storage, no migration
- Tools grid and users admin stay bespoke pages
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class Scope(enum.Enum):
    """Storage tier of a setting, in precedence order."""

    SESSION = "session"
    USER = "user"
    GLOBAL = "global"


class Role(enum.IntEnum):
    """User role; ordering makes `>=` a minimum-role check.

    - GUEST < CHAT < CODE < OWNER
    - Owner-only settings are hidden from everyone else
    """

    GUEST = 0
    CHAT = 1
    CODE = 2
    OWNER = 3


class Access(enum.Enum):
    """Owner-set per-option access level for each user.

    - Layers on top of `view_role`/`edit_role` gates
    - `HIDDEN`: invisible, global value applies silently
    - `READONLY`: visible but not editable
    - `DELEGATED`: user sees and edits own values
    """

    HIDDEN = "hidden"
    READONLY = "readonly"
    DELEGATED = "delegated"


# Default base access per option; absent means DELEGATED.
# - Owner can override at runtime, stored in db
# - Per-user exceptions come from the allowlist
BASE_ACCESS_DEFAULTS: dict[str, Access] = {
    "model": Access.DELEGATED,
    "effort": Access.DELEGATED,           # `max` is further gated
    "permission_mode": Access.DELEGATED,  # Delegated to code users too
    "max_turns": Access.DELEGATED,
    "sandbox": Access.HIDDEN,            # Owner delegates
    "language": Access.DELEGATED,
    "usage_display": Access.READONLY,    # Account-wide; owner delegates
    "tools": Access.DELEGATED,
    "hot_cache_timer": Access.DELEGATED,  # Every user may toggle their note
    "todo_card": Access.DELEGATED,        # Code users toggle the task-list card
    "auto_compact": Access.HIDDEN,        # Forced on; owner may disable
    "ctx_status": Access.HIDDEN,          # Forced on; owner may disable
}


def _coerce_access(v) -> Optional[Access]:
    """Map a stored string or Access to Access, else None."""
    if isinstance(v, Access):
        return v
    try:
        return Access(str(v).strip().lower())
    except (ValueError, AttributeError):
        return None


@dataclass
class Ctx:
    """Context the adapters and resolver read.

    - `state` may be None when no session is bound
    - Carries user id, role, settings and allowlist
    """

    state: Any = None              # `db.ThreadState` or None
    user_id: Optional[int] = None
    role: Role = Role.GUEST
    settings: Any = None           # `config.Settings` or None
    allowlist: Any = None          # `Allowlist` or None

    def session_owner(self) -> Optional[int]:
        """UID owning the bound session, else the acting user.

        - Used for USER-scope reads keyed on session owner
        """
        st = self.state
        if st is not None:
            return getattr(st, "created_by", None) or getattr(st, "chat_id", None)
        return self.user_id


# Getters return value or None; setters may be async.
Getter = Callable[[Ctx], Any]
Setter = Callable[[Ctx, Any], Any]


@dataclass(frozen=True)
class Setting:
    """One single-value setting in the unified registry.

    - `get`/`set` are per-scope adapters over existing storage
    - `view_role`/`edit_role` are minimum roles, rechecked on apply
    - `choices` None means open value
    """

    key: str
    type: type
    choices: Optional[tuple]
    default: Any
    scopes: tuple
    view_role: Role
    edit_role: Role
    name_key: str
    value_labels: dict = field(default_factory=dict)
    get: dict = field(default_factory=dict)   # `dict[Scope, Getter]`
    set: dict = field(default_factory=dict)   # `dict[Scope, Setter]`

    def can_view(self, role: Role) -> bool:
        return role >= self.view_role

    def can_edit(self, role: Role) -> bool:
        """Server-side authorization for an edit.

        - Every apply path must recheck before mutating storage
        """
        return role >= self.edit_role


def resolve(setting: "Setting", ctx: Ctx) -> tuple[Any, Scope]:
    """Resolve the effective value of a setting.

    - Walks SESSION, USER, GLOBAL; first non-None wins
    - Returns `(value, source_scope)`; falls back to default
    - Per-setting quirks live in adapters, not here
    """
    return resolve_from(setting, ctx, Scope.SESSION)


_PRECEDENCE = (Scope.SESSION, Scope.USER, Scope.GLOBAL)


def resolve_from(setting: "Setting", ctx: Ctx, start: Scope) -> tuple[Any, Scope]:
    """Like `resolve`, but starts at a given scope.

    - USER/GLOBAL tabs must not surface session overrides
    """
    started = False
    for scope in _PRECEDENCE:
        if scope == start:
            started = True
        if not started:
            continue
        getter = setting.get.get(scope)
        if getter is None:
            continue
        value = getter(ctx)
        if value is not None:
            return value, scope
    return setting.default, Scope.GLOBAL


# Access model: owner-configured, derived per prompt.
def effective_access(setting: "Setting", ctx: "Ctx") -> Access:
    """Owner-configured access of a setting for the user.

    - Owner is always DELEGATED
    - Else per-user exception, base override, default, DELEGATED
    - Both dicts are preloaded into the context
    """
    if ctx.role >= Role.OWNER:
        return Access.DELEGATED
    exc = getattr(ctx, "access_exceptions", None)
    if isinstance(exc, dict):
        a = _coerce_access(exc.get(setting.key))
        if a is not None:
            return a
    base = getattr(ctx, "access_base", None)
    if isinstance(base, dict):
        a = _coerce_access(base.get(setting.key))
        if a is not None:
            return a
    return BASE_ACCESS_DEFAULTS.get(setting.key, Access.DELEGATED)


def can_view_setting(setting: "Setting", ctx: "Ctx") -> bool:
    """Visible iff role passes gate and access is not HIDDEN."""
    return setting.can_view(ctx.role) and effective_access(setting, ctx) != Access.HIDDEN


def can_edit_setting(setting: "Setting", ctx: "Ctx") -> bool:
    """Editable iff role passes gate and access is DELEGATED.

    - Re-checked server-side on every apply; buttons are not authorization
    """
    return setting.can_edit(ctx.role) and effective_access(setting, ctx) == Access.DELEGATED


def configured_base_access(setting: "Setting", ctx: "Ctx") -> Access:
    """Owner-configured base access, independent of the viewer.

    - Feeds the owner's access editor
    - Unlike `effective_access`, owner is not forced DELEGATED
    """
    base = getattr(ctx, "access_base", None)
    if isinstance(base, dict):
        a = _coerce_access(base.get(setting.key))
        if a is not None:
            return a
    return BASE_ACCESS_DEFAULTS.get(setting.key, Access.DELEGATED)


def resolve_effective(setting: "Setting", ctx: "Ctx") -> tuple[Any, Scope]:
    """Effective value honoring the user's access level.

    - DELEGATED walks SESSION, USER, GLOBAL; otherwise global only
    - Stored overrides are kept but ignored when lowered
    """
    if effective_access(setting, ctx) == Access.DELEGATED:
        return resolve(setting, ctx)
    return resolve_from(setting, ctx, Scope.GLOBAL)


# ---- USER-scope adapters ----
# - USER getter reads a preloaded user-defaults dict on `ctx`
# - Keeps `resolve()` synchronous on the hot path
# - A factory binds each setting's key
def _user_get(key: str) -> Getter:
    def getter(ctx: Ctx):
        defaults = getattr(ctx, "user_defaults", None)
        if isinstance(defaults, dict):
            return defaults.get(key)
        return None

    return getter


# ---- Per-setting adapters ----
def _session_attr_get(attr: str) -> Getter:
    """SESSION getter reading a `ThreadState` attribute.

    - Returns None when there is no state
    """
    def getter(ctx: Ctx):
        return getattr(ctx.state, attr, None) if ctx.state is not None else None

    return getter


# ---- sandbox: inverted override ----
# - Session `no_sandbox` is a negative override over a positive global
# - Inversion lives in the adapter; `resolve` stays generic
# - SESSION getter: False if `no_sandbox`, else None
# - GLOBAL getter: `settings.sandbox_code`, default True
def _sandbox_session_get(ctx: Ctx):
    st = ctx.state
    if st is not None and getattr(st, "no_sandbox", False):
        return False
    return None


def _sandbox_global_get(ctx: Ctx):
    s = ctx.settings
    return bool(getattr(s, "sandbox_code", True)) if s is not None else None


def _bool_user_get(key: str) -> Getter:
    """USER getter coercing stored default to bool or None."""
    base = _user_get(key)

    def getter(ctx: Ctx):
        v = base(ctx)
        return None if v is None else bool(v)

    return getter


# ---- Scope setters ----
# - Setter writes a value into one scope's storage
# - `db` imported lazily to avoid an import cycle
# - Apply handler rechecks `edit_role`; buttons are not authorization
# - None value clears the scope
def _session_attr_setter(db_func_name: str) -> Setter:
    """SESSION setter calling the matching async `db.set_<x>` helper.

    - No-op when no session is bound
    """
    async def setter(ctx: Ctx, value):
        from app.storage import db  # Lazy: avoids an import cycle
        st = ctx.state
        if st is None:
            return
        thread_id = getattr(st, "thread_id", None)
        if thread_id is None:
            return
        func = getattr(db, db_func_name)
        await func(thread_id, value)

    return setter


def _user_setter(key: str) -> Setter:
    """USER setter persisting the per-user default.

    - Value None clears it
    """
    async def setter(ctx: Ctx, value):
        from app.storage import db  # Lazy import
        if ctx.user_id is None:
            return
        await db.set_user_default(ctx.user_id, key, value)

    return setter


def _model_global_setter() -> Setter:
    """GLOBAL model setter mutating the live default.

    - Runtime only; re-read from `.env` on restart
    - Owner-gated in the apply path
    """
    def setter(ctx: Ctx, value):
        if ctx.settings is not None and value is not None:
            ctx.settings.default_model = value

    return setter


def _sandbox_session_setter() -> Setter:
    """SESSION sandbox setter, owner-only.

    - Stored column is inverted opt-out `no_sandbox`
    - True maps to False, False to True, None clears
    - Mirrors `_sandbox_session_get` so `resolve` stays generic
    """
    async def setter(ctx: Ctx, value):
        from app.storage import db  # Lazy import
        st = ctx.state
        thread_id = getattr(st, "thread_id", None) if st is not None else None
        if thread_id is None:
            return
        await db.set_no_sandbox(thread_id, value is False)

    return setter


def _sandbox_global_setter() -> Setter:
    """GLOBAL sandbox setter, owner-only.

    - Runtime only; `SANDBOX_CODE` is re-read on restart
    """
    def setter(ctx: Ctx, value):
        if ctx.settings is not None and value is not None:
            ctx.settings.sandbox_code = bool(value)

    return setter


def _language_user_setter() -> Setter:
    """USER language setter writing to its own store.

    - Uses `db.set_user_lang`, not the generic user-default store
    """
    async def setter(ctx: Ctx, value):
        from app.storage import db  # Lazy import
        if ctx.user_id is None or value is None:
            return
        await db.set_user_lang(ctx.user_id, value)

    return setter


# Permission modes are the SDK literals.
# - Effort levels come from the CLI per model
# - 'default'/ask dropped; auto-edits is the floor
# - Full-access is ungated for code users; sandbox contains it
_PERM_CHOICES = ("acceptEdits", "plan", "bypassPermissions")


SETTINGS: dict[str, Setting] = {
    "model": Setting(
        key="model",
        type=str,
        # Model choices are open here.
        # - Offered set is the CLI's own model catalog
        choices=None,
        default=None,  # Global scope always answers
        scopes=(Scope.SESSION, Scope.USER, Scope.GLOBAL),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_model",
        get={
            Scope.SESSION: _session_attr_get("model"),
            Scope.USER: _user_get("model"),
            Scope.GLOBAL: lambda ctx: (
                getattr(ctx.settings, "default_model", None)
                if ctx.settings is not None else None
            ),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_model"),
            Scope.USER: _user_setter("model"),
            Scope.GLOBAL: _model_global_setter(),
        },
    ),
    "effort": Setting(
        key="effort",
        type=str,
        choices=None,  # CLI levels for the session's model
        default=None,  # None means SDK default effort
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_effort",
        get={
            Scope.SESSION: _session_attr_get("effort"),
            Scope.USER: _user_get("effort"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_effort"),
            Scope.USER: _user_setter("effort"),
        },
    ),
    "permission_mode": Setting(
        key="permission_mode",
        type=str,
        choices=_PERM_CHOICES,
        # Baseline `acceptEdits`: jail contains in-jail work.
        # - Prompts only for outbound or destructive actions
        default="acceptEdits",
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CODE,
        edit_role=Role.CODE,
        name_key="settings.row_perm",
        get={
            Scope.SESSION: _session_attr_get("permission_mode"),
            Scope.USER: _user_get("permission_mode"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_permission_mode"),
            Scope.USER: _user_setter("permission_mode"),
        },
    ),
    # Retired rows: 1M-context toggle and streaming toggle.
    # - Native draft streaming is always on
    # - `big_memory` and `stream_enabled` columns and setters remain
    "max_turns": Setting(
        key="max_turns",
        type=int,
        choices=None,  # Free integer; None means unlimited
        default=None,
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CODE,
        edit_role=Role.CODE,
        name_key="settings.row_maxturns",
        get={
            Scope.SESSION: _session_attr_get("max_turns"),
            Scope.USER: _user_get("max_turns"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_max_turns"),
            Scope.USER: _user_setter("max_turns"),
        },
    ),
    "language": Setting(
        key="language",
        type=str,
        choices=None,  # Supported locale set, open here
        default="en",
        scopes=(Scope.USER, Scope.GLOBAL),
        view_role=Role.GUEST,
        edit_role=Role.GUEST,
        name_key="lang.row",
        get={
            # Language is per-user; USER tier reads preloaded default.
            # - GLOBAL falls back to the bot default language
            Scope.USER: _user_get("language"),
        },
        set={
            # Language has its own store, `lang:<uid>` kv.
            # - USER setter writes there, not generic user-default
            # - Handler refreshes locale cache and menu after
            Scope.USER: _language_user_setter(),
        },
    ),
    "sandbox": Setting(
        key="sandbox",
        type=bool,
        choices=(True, False),
        default=True,  # Sandbox on by default
        scopes=(Scope.SESSION, Scope.USER, Scope.GLOBAL),
        # Owner-only and hidden from non-owners.
        # - It spends the owner's one subscription
        # - The jail protects the deployer's box
        view_role=Role.OWNER,
        edit_role=Role.OWNER,
        name_key="settings.row_sandbox",
        value_labels={},
        get={
            Scope.SESSION: _sandbox_session_get,
            Scope.USER: _bool_user_get("sandbox"),
            Scope.GLOBAL: _sandbox_global_get,
        },
        set={
            Scope.SESSION: _sandbox_session_setter(),
            Scope.USER: _user_setter("sandbox"),
            Scope.GLOBAL: _sandbox_global_setter(),
        },
    ),
    # Post-reply warm-cache note; delegated to every user.
    # - Owner can re-gate it via the access model
    "hot_cache_timer": Setting(
        key="hot_cache_timer",
        type=bool,
        choices=(True, False),
        default=False,
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_hot_cache_timer",
        value_labels={},
        get={
            Scope.SESSION: _session_attr_get("hot_cache_timer"),
            Scope.USER: _bool_user_get("hot_cache_timer"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_hot_cache_timer"),
            Scope.USER: _user_setter("hot_cache_timer"),
        },
    ),
    # Live task-list card from `TodoWrite` events.
    # - Per-session and per-user bool, default off
    # - Code-only: chat has no tools
    "todo_card": Setting(
        key="todo_card",
        type=bool,
        choices=(True, False),
        default=False,
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CODE,
        edit_role=Role.CODE,
        name_key="settings.row_todo_card",
        value_labels={},
        get={
            Scope.SESSION: _session_attr_get("todo_card"),
            Scope.USER: _bool_user_get("todo_card"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_todo_card"),
            Scope.USER: _user_setter("todo_card"),
        },
    ),
    # SDK auto-compaction: on by default, disableable if delegated.
    # - USER-scope only, not per-session
    # - A session bool defaults off, wrongly overriding forced-on
    # - Wired via the `DISABLE_AUTO_COMPACT` env in the engine
    "auto_compact": Setting(
        key="auto_compact",
        type=bool,
        choices=(True, False),
        default=True,
        scopes=(Scope.USER,),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_auto_compact",
        value_labels={},
        get={Scope.USER: _bool_user_get("auto_compact")},
        set={Scope.USER: _user_setter("auto_compact")},
    ),
    # Live context size in the working plate.
    # - Forced on, disableable if delegated; USER-scope
    "ctx_status": Setting(
        key="ctx_status",
        type=bool,
        choices=(True, False),
        default=True,
        scopes=(Scope.USER,),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_ctx_status",
        value_labels={},
        get={Scope.USER: _bool_user_get("ctx_status")},
        set={Scope.USER: _user_setter("ctx_status")},
    ),
}


# Import-time check: `edit_role` must be at least `view_role`.
# - Apply path gates on `can_edit` only
# - Turns an editable-but-unviewable footgun into startup failure
for _k, _s in SETTINGS.items():
    assert _s.edit_role >= _s.view_role, (
        f"settings_schema: {_k!r} has edit_role {_s.edit_role.name} < view_role "
        f"{_s.view_role.name}; an apply could mutate a value the user can't view"
    )


def get(key: str) -> Setting:
    """Return the registered Setting for `key`.

    - Raises `KeyError` if unknown
    """
    return SETTINGS[key]


# Settings that apply only to code sessions.
# - They need a workdir or the agent toolset
# - Hub hides them on the SESSION tab for chat sessions
# - Gated on session mode, not user level
# - USER/GLOBAL tabs still show them as future defaults
# - `sandbox` is excluded: the jail covers chat too
CODE_ONLY: frozenset[str] = frozenset({"permission_mode", "max_turns", "todo_card"})


def is_code_only(key: str) -> bool:
    """Whether `key` applies only to code sessions."""
    return key in CODE_ONLY


# Order settings appear on a scope page.
# - Stable, most-used first
PAGE_ORDER: tuple[str, ...] = (
    "model", "effort", "permission_mode", "max_turns",
    # Sandbox row is hidden: the sandbox is always on.
    # - The `sandbox` setting still drives resolution
    "language",
    # Warm-cache note, auto-compact, live context rows.
    # - Forced-on rows are disableable when delegated
    "hot_cache_timer", "auto_compact", "ctx_status",
    # Live task-list card row (delegated, code-only).
    "todo_card",
)


def role_for(is_owner: bool, level: Optional[str], may_max_effort: bool = False) -> Role:
    """Map access primitives to a registry `Role`.

    - Owner is OWNER, code user is CODE, others CHAT
    - GUEST is only the resolver default
    - `may_max_effort` is unused; kept for call symmetry
    """
    if is_owner:
        return Role.OWNER
    if level == "code":
        return Role.CODE
    return Role.CHAT


def settings_for_scope(scope: "Scope", role: Role) -> list["Setting"]:
    """Settings visible to `role` at `scope`, in page order.

    - Must declare the scope and pass the `view_role` gate
    """
    out: list[Setting] = []
    for key in PAGE_ORDER:
        s = SETTINGS.get(key)
        if s is None:
            continue
        if scope in s.scopes and s.can_view(role):
            out.append(s)
    return out


def make_ctx(state=None, user_id=None, role=Role.GUEST, settings=None,
             allowlist=None, user_defaults=None, access_base=None,
             access_exceptions=None) -> Ctx:
    """Build a resolution context.

    - `user_defaults` preloads the synchronous USER-scope getters
    - `access_base` and `access_exceptions` feed the access resolver
    """
    ctx = Ctx(state=state, user_id=user_id, role=role, settings=settings,
              allowlist=allowlist)
    # Attach optional preloaded user-defaults for USER getters.
    ctx.user_defaults = user_defaults if isinstance(user_defaults, dict) else {}
    # Attach preloaded access config: owner overrides and exceptions.
    ctx.access_base = access_base if isinstance(access_base, dict) else {}
    ctx.access_exceptions = access_exceptions if isinstance(access_exceptions, dict) else {}
    return ctx
