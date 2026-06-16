"""Unified settings registry + resolver (#138, PART 1 — foundation).

This module is the single source of truth for the bot's user-facing settings: WHAT
each setting is (key, type, choices, default), WHERE it lives across the three
storage tiers, WHO may see/edit it, and HOW to resolve its effective value.

Three SCOPES, with a fixed precedence (SESSION → USER → GLOBAL → built-in default):

* ``SESSION`` — this session only (``db.ThreadState`` columns + setters).
* ``USER``    — the user's personal default for their FUTURE sessions (the NEW tier,
  stored generically via ``db.get_user_default`` / ``db.set_user_default``).
* ``GLOBAL``  — the deployer/owner-wide value (``config.Settings`` + allowlist owner
  prefs); the built-in fallback when nothing else is set.

``resolve(setting, ctx)`` walks SESSION → USER → GLOBAL and returns the FIRST
non-None value with its source scope, else ``(setting.default, Scope.GLOBAL)``.
Each setting carries per-scope adapter callables over the EXISTING storage, so there
is ZERO data migration and the resolver itself stays generic — any per-setting
quirk (e.g. the sandbox override inversion) lives INSIDE that setting's adapter.

PART 2 builds the generic /settings renderer on top of this registry. The tools
toggle GRID and the users-admin flows are NOT single-value settings and are
DELIBERATELY left out of ``SETTINGS`` — they remain bespoke pages reachable from
the settings menu (see module-level note below).

NOTE for PART 2 — bespoke (non-registry) pages reachable from /settings:
    * tools          — a multi-select toggle GRID (db.set_tools_enabled), not one value.
    * users / admin  — per-user access level / usage limits / tool caps (allowlist),
                       owner-only multi-record admin, not one value.
These keep their own dedicated pages; the registry only owns single-value settings.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class Scope(enum.Enum):
    """Storage tier of a setting value, in precedence order (SESSION wins)."""

    SESSION = "session"
    USER = "user"
    GLOBAL = "global"


class Role(enum.IntEnum):
    """A user's role, ordered so ``>=`` is a "min role" comparison.

    GUEST < CHAT < CODE < OWNER. Used by ``view_role`` / ``edit_role`` gates: a user
    may see/edit a setting iff their role is ``>=`` the setting's required role. The
    OWNER-only settings (sandbox, global memory, global default model, per-user
    admin) require ``Role.OWNER`` and are therefore HIDDEN from everyone else.
    """

    GUEST = 0
    CHAT = 1
    CODE = 2
    OWNER = 3


class Access(enum.Enum):
    """Owner-controlled per-option, per-user access level (#151, menu.md §4.2).

    The ladder: *grant it → let them use it · otherwise read-only · otherwise they
    never see it.* This LAYERS ON TOP of the structural ``view_role``/``edit_role``
    gate (which encodes code-level / owner-only capability): a setting is VISIBLE iff
    ``role >= view_role`` AND access != HIDDEN; EDITABLE iff ``role >= edit_role`` AND
    access == DELEGATED.

    * ``HIDDEN``    — user never sees it; rides the global value silently.
    * ``READONLY``  — user sees it but can't change it; value is global.
    * ``DELEGATED`` — user sees AND changes it (own default + per session); their own
      value counts (session → user default → global), until set they ride global.
    """

    HIDDEN = "hidden"
    READONLY = "readonly"
    DELEGATED = "delegated"


# Default BASE access per option (menu.md Table 23). Absent ⇒ DELEGATED. The owner
# can override any of these at runtime (stored in db; preloaded into Ctx.access_base)
# and can add per-user EXCEPTIONS (allowlist; preloaded into Ctx.access_exceptions).
BASE_ACCESS_DEFAULTS: dict[str, Access] = {
    "model": Access.DELEGATED,
    "effort": Access.DELEGATED,           # `max` further gated (allow_max_effort)
    "permission_mode": Access.DELEGATED,  # `full-access` is owner-only
    "max_turns": Access.DELEGATED,
    "memory": Access.HIDDEN,              # big_memory: owner delegates to granted users
    "sandbox": Access.HIDDEN,            # owner delegates
    "language": Access.DELEGATED,
    "usage_display": Access.READONLY,    # account-wide; owner delegates
    "tools": Access.DELEGATED,
}


def _coerce_access(v) -> Optional[Access]:
    """Map a stored string / Access to an Access (or None when unrecognized)."""
    if isinstance(v, Access):
        return v
    try:
        return Access(str(v).strip().lower())
    except (ValueError, AttributeError):
        return None


@dataclass
class Ctx:
    """The small context the adapters/resolver read.

    Carries everything an adapter needs to GET/SET a value across scopes WITHOUT
    importing handler state: the session ``state`` (a ``db.ThreadState`` or None),
    the acting ``user_id``, the user's ``role``, plus the shared ``settings``
    (config.Settings) and ``allowlist`` singletons. ``state`` may be None when a
    page is opened with no session bound (USER/GLOBAL scopes still resolve).
    """

    state: Any = None              # db.ThreadState | None
    user_id: Optional[int] = None
    role: Role = Role.GUEST
    settings: Any = None           # config.Settings | None
    allowlist: Any = None          # allowlist.Allowlist | None

    def session_owner(self) -> Optional[int]:
        """The uid that owns the bound session (DM creator == chat_id), else the
        acting user. Used for USER-scope reads keyed on the session's owner."""
        st = self.state
        if st is not None:
            return getattr(st, "created_by", None) or getattr(st, "chat_id", None)
        return self.user_id


# An adapter is ``get(ctx) -> value | None`` or ``set(ctx, value) -> None|awaitable``.
Getter = Callable[[Ctx], Any]
Setter = Callable[[Ctx, Any], Any]


@dataclass(frozen=True)
class Setting:
    """One single-value setting in the unified registry.

    * ``key``          — stable id (the user-default kv key + callback token).
    * ``type``         — value type (``str`` / ``int`` / ``bool``).
    * ``choices``      — a fixed tuple of allowed values, or None (free/open value).
    * ``default``      — the built-in fallback used when no scope has a value.
    * ``scopes``       — which scopes this setting is stored in (subset, ordered).
    * ``view_role`` / ``edit_role`` — min ``Role`` to SEE / EDIT (re-checked in apply).
    * ``name_key``     — i18n row for the display label.
    * ``value_labels`` — optional {raw_value: i18n_key_or_text} for friendly labels.
    * ``get`` / ``set``— per-scope adapter callables over the EXISTING storage.
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
    get: dict = field(default_factory=dict)   # dict[Scope, Getter]
    set: dict = field(default_factory=dict)   # dict[Scope, Setter]

    def can_view(self, role: Role) -> bool:
        return role >= self.view_role

    def can_edit(self, role: Role) -> bool:
        """SERVER-SIDE authorization for an edit. A button is NOT authorization —
        every apply path MUST re-check this before mutating storage (#138)."""
        return role >= self.edit_role


def resolve(setting: "Setting", ctx: Ctx) -> tuple[Any, Scope]:
    """Resolve the effective value of ``setting`` for ``ctx``.

    Walks the scopes in precedence order SESSION → USER → GLOBAL and returns the
    FIRST scope whose getter yields a non-None value, as ``(value, source_scope)``.
    If every scope is None (or has no adapter), returns ``(setting.default,
    Scope.GLOBAL)``. The walk is generic: any per-setting inversion/quirk lives
    inside that setting's adapter, not here.
    """
    return resolve_from(setting, ctx, Scope.SESSION)


_PRECEDENCE = (Scope.SESSION, Scope.USER, Scope.GLOBAL)


def resolve_from(setting: "Setting", ctx: Ctx, start: Scope) -> tuple[Any, Scope]:
    """Like ``resolve`` but only considers ``start`` and the scopes BELOW it in
    precedence (#138-fix). The full hub (SESSION tab) wants the effective value via
    ``resolve``; the USER / GLOBAL tabs want "what THIS scope contributes, or what it
    inherits from below" — walking from SESSION there would wrongly surface a
    session override on the "my defaults" page. Falls back to (default, GLOBAL)."""
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


# --------------------------------------------------------------------------- #
# Access model (#151, menu.md §4) — owner-configured, DERIVED per prompt.
# --------------------------------------------------------------------------- #
def effective_access(setting: "Setting", ctx: "Ctx") -> Access:
    """The owner-configured access of ``setting`` for ctx's user (#151, menu.md §4.2).

    Resolution: OWNER is always DELEGATED (manages global + rules, edits own values
    freely). Otherwise per-user EXCEPTION (``ctx.access_exceptions``) → owner's BASE
    override (``ctx.access_base``) → the built-in default (``BASE_ACCESS_DEFAULTS``)
    → DELEGATED. Both dicts are preloaded into the Ctx (kept sync for the hot path)."""
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
    """Visible iff the role passes the structural gate AND access != HIDDEN (#151)."""
    return setting.can_view(ctx.role) and effective_access(setting, ctx) != Access.HIDDEN


def can_edit_setting(setting: "Setting", ctx: "Ctx") -> bool:
    """Editable iff the role passes the structural gate AND access == DELEGATED (#151).
    Re-checked server-side in every apply path — a button is never authorization."""
    return setting.can_edit(ctx.role) and effective_access(setting, ctx) == Access.DELEGATED


def configured_base_access(setting: "Setting", ctx: "Ctx") -> Access:
    """The owner-CONFIGURED base access for ``setting`` (the owner's override → the
    built-in default), independent of who is viewing — feeds the owner's access
    editor (#151, menu.md §4.4). Distinct from ``effective_access`` (which returns
    DELEGATED for the owner viewing their own values)."""
    base = getattr(ctx, "access_base", None)
    if isinstance(base, dict):
        a = _coerce_access(base.get(setting.key))
        if a is not None:
            return a
    return BASE_ACCESS_DEFAULTS.get(setting.key, Access.DELEGATED)


def resolve_effective(setting: "Setting", ctx: "Ctx") -> tuple[Any, Scope]:
    """The DERIVED effective value honoring access (#151 soft-revoke, menu.md §4.6):
    when the user is DELEGATED the value walks SESSION → USER → GLOBAL; otherwise
    ONLY the global value counts (the user's stored session/user overrides are kept
    but no longer counted, so lowering access falls back to global immediately)."""
    if effective_access(setting, ctx) == Access.DELEGATED:
        return resolve(setting, ctx)
    return resolve_from(setting, ctx, Scope.GLOBAL)


# --------------------------------------------------------------------------- #
# USER-scope adapters (generic, shared by every registry key)
# --------------------------------------------------------------------------- #
# The USER tier is a synchronous READ from the per-user-default cache the handler
# layer must keep warm, plus an ASYNC write. To keep ``resolve()`` synchronous (it
# runs on the hot path) the USER getter reads from ``ctx`` if a preloaded
# user-defaults dict is attached, falling back to None. PART 2 wires the preload +
# the async set; PART 1 only needs the GETTER to participate so resolve() can walk
# the tier. We expose a factory so each setting binds its own key.
def _user_get(key: str) -> Getter:
    def getter(ctx: Ctx):
        defaults = getattr(ctx, "user_defaults", None)
        if isinstance(defaults, dict):
            return defaults.get(key)
        return None

    return getter


# --------------------------------------------------------------------------- #
# Per-setting adapters
# --------------------------------------------------------------------------- #
def _session_attr_get(attr: str) -> Getter:
    """SESSION getter reading a ``db.ThreadState`` attribute (None when no state)."""
    def getter(ctx: Ctx):
        return getattr(ctx.state, attr, None) if ctx.state is not None else None

    return getter


# -- sandbox: the confusing one (#138) --------------------------------------- #
# OLD effective decision (sessions.py ~213): ``settings.sandbox_code and not
# state.no_sandbox`` — a NEGATIVE per-session override (no_sandbox) over a positive
# global. We route it through the registry so the inversion lives in the ADAPTER and
# resolve() stays generic:
#   * SESSION getter: returns False when state.no_sandbox is set (an explicit
#     override-OFF), else None (no session-level opinion → fall through).
#   * USER getter (owner-only edit): a per-user default sandbox bool, or None.
#   * GLOBAL getter: settings.sandbox_code (the deployer-wide value); default True.
def _sandbox_session_get(ctx: Ctx):
    st = ctx.state
    if st is not None and getattr(st, "no_sandbox", False):
        return False
    return None


def _sandbox_global_get(ctx: Ctx):
    s = ctx.settings
    return bool(getattr(s, "sandbox_code", True)) if s is not None else None


def _bool_user_get(key: str) -> Getter:
    """USER getter coercing a stored user-default to a real bool (or None)."""
    base = _user_get(key)

    def getter(ctx: Ctx):
        v = base(ctx)
        return None if v is None else bool(v)

    return getter


# --------------------------------------------------------------------------- #
# Scope SETTERS (#138, PART 2) — write a value into one scope's storage.
# --------------------------------------------------------------------------- #
# Mirror the getters: a setter is ``set(ctx, value) -> awaitable`` writing to the
# scope's backing store over the EXISTING db/config helpers (ZERO migration). They
# import ``db`` LAZILY so this module stays import-cycle-free (db never imports it).
# The generic apply handler RE-CHECKS ``edit_role`` before ever calling a setter
# (the button is not authorization, AGENTS §2 / #138). A None value CLEARS the
# scope (falls through to the next tier in resolve()).
def _session_attr_setter(db_func_name: str) -> Setter:
    """SESSION setter calling the matching ``db.set_<x>(thread_id, value)`` async
    helper for the bound session (no-op when no session is bound)."""
    async def setter(ctx: Ctx, value):
        import db  # lazy: avoid an import cycle
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
    """USER setter persisting the per-user default (value None CLEARS it)."""
    async def setter(ctx: Ctx, value):
        import db  # lazy
        if ctx.user_id is None:
            return
        await db.set_user_default(ctx.user_id, key, value)

    return setter


def _model_global_setter() -> Setter:
    """GLOBAL model setter — mutates the live deployer default (runtime only; it
    re-reads from .env on the next process start). Owner-gated in the apply path."""
    def setter(ctx: Ctx, value):
        if ctx.settings is not None and value is not None:
            ctx.settings.default_model = value

    return setter


def _sandbox_session_setter() -> Setter:
    """SESSION sandbox setter (owner-only). The stored column is the INVERTED
    opt-OUT (``no_sandbox``): value True (isolate) → no_sandbox False, value False
    (raw) → no_sandbox True, value None → re-isolate (clear the opt-out). Mirrors
    the inversion in ``_sandbox_session_get`` so resolve() stays generic."""
    async def setter(ctx: Ctx, value):
        import db  # lazy
        st = ctx.state
        thread_id = getattr(st, "thread_id", None) if st is not None else None
        if thread_id is None:
            return
        await db.set_no_sandbox(thread_id, value is False)

    return setter


def _sandbox_global_setter() -> Setter:
    """GLOBAL sandbox setter (owner-only) — mutates the live deployer-wide value
    (runtime only; it re-reads SANDBOX_CODE from .env on the next start)."""
    def setter(ctx: Ctx, value):
        if ctx.settings is not None and value is not None:
            ctx.settings.sandbox_code = bool(value)

    return setter


def _language_user_setter() -> Setter:
    """USER language setter — persists the locale to its OWN kv store
    (db.set_user_lang, key lang:<uid>), not the generic user_default kv."""
    async def setter(ctx: Ctx, value):
        import db  # lazy
        if ctx.user_id is None or value is None:
            return
        await db.set_user_lang(ctx.user_id, value)

    return setter


# Effort choices/levels live in handlers.EFFORT_LEVELS; permission modes are the
# SDK literals. Kept as literals here to avoid importing the handler layer (which
# imports this module would risk a cycle) — PART 2 maps friendly labels via i18n.
_EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max")
_PERM_CHOICES = ("default", "acceptEdits", "plan", "bypassPermissions")


SETTINGS: dict[str, Setting] = {
    "model": Setting(
        key="model",
        type=str,
        choices=("opus", "sonnet", "haiku"),
        default="opus",
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
        choices=_EFFORT_CHOICES,
        default=None,  # None = SDK default (no explicit effort)
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
        default="default",
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
    "memory": Setting(
        key="memory",  # per-session big_memory (1M context window)
        type=bool,
        choices=(True, False),
        default=False,
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CHAT,
        edit_role=Role.CHAT,
        name_key="settings.row_memory",
        get={
            Scope.SESSION: _session_attr_get("big_memory"),
            Scope.USER: _bool_user_get("memory"),
        },
        set={
            Scope.SESSION: _session_attr_setter("set_big_memory"),
            Scope.USER: _user_setter("memory"),
        },
    ),
    # #144: the Streaming toggle is RETIRED — native Telegram sendMessageDraft
    # streaming is always-on (no user toggle; AGENTS §5), and /stream is gone. The
    # registry row is removed so the /settings hub no longer renders it. The
    # ThreadState.stream_enabled column + db setter are kept (harmless) for revert.
    # "stream_enabled": Setting(
    #     key="stream_enabled",
    #     type=bool,
    #     choices=(True, False),
    #     default=True,
    #     scopes=(Scope.SESSION, Scope.USER),
    #     view_role=Role.CHAT,
    #     edit_role=Role.CHAT,
    #     name_key="settings.row_streaming",
    #     get={
    #         Scope.SESSION: _session_attr_get("stream_enabled"),
    #         Scope.USER: _bool_user_get("stream_enabled"),
    #     },
    #     set={
    #         Scope.SESSION: _session_attr_setter("set_stream_enabled"),
    #         Scope.USER: _user_setter("stream_enabled"),
    #     },
    # ),
    "max_turns": Setting(
        key="max_turns",
        type=int,
        choices=None,  # free integer (None = unlimited)
        default=None,
        scopes=(Scope.SESSION, Scope.USER),
        view_role=Role.CODE,
        edit_role=Role.CODE,
        name_key="settings.row_maxturns",  # #140-fix: was settings.row_model (dup "Model" row)
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
        choices=None,  # the supported-locale set (i18n.LANGUAGES) — open here
        default="en",
        scopes=(Scope.USER, Scope.GLOBAL),
        view_role=Role.GUEST,
        edit_role=Role.GUEST,
        name_key="lang.row",
        get={
            # Language is a per-USER preference (kv lang:<uid>); the USER tier reads
            # the preloaded user-default, GLOBAL falls back to the bot default lang.
            Scope.USER: _user_get("language"),
        },
        set={
            # Language has its OWN store (kv lang:<uid>, db.set_user_lang) so the
            # USER setter writes there rather than the generic user_default kv; the
            # handler still updates the locale cache + per-chat menu after the call.
            Scope.USER: _language_user_setter(),
        },
    ),
    "sandbox": Setting(
        key="sandbox",
        type=bool,
        choices=(True, False),
        default=True,  # sandbox ON by default (#136)
        scopes=(Scope.SESSION, Scope.USER, Scope.GLOBAL),
        # OWNER-ONLY + HIDDEN from non-owners: it spends/exposes the owner's ONE
        # subscription and the jail protects the deployer's box (#138).
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
}


# #138-fix (security defense-in-depth): enforce edit_role >= view_role for EVERY
# setting at import time. The apply path gates on can_edit only; this invariant is
# what makes that safe (you can't edit what you can't view). Asserting it here turns
# a future "editable but not viewable" footgun into a loud startup failure instead
# of a silent gate bypass.
for _k, _s in SETTINGS.items():
    assert _s.edit_role >= _s.view_role, (
        f"settings_schema: {_k!r} has edit_role {_s.edit_role.name} < view_role "
        f"{_s.view_role.name}; an apply could mutate a value the user can't view"
    )


def get(key: str) -> Setting:
    """Return the registered Setting for ``key`` (raises KeyError if unknown)."""
    return SETTINGS[key]


# Settings that ONLY apply to a CODE session (menu.md §1.7 / Table 23 "Applies to:
# code") — they need a working directory or the agent toolset. The /settings hub
# hides these rows on the SESSION tab when the bound session is a chat, gating on
# the session MODE (not the user's level): a code-level user in a chat session
# should not see Permissions / Max turns / Sandbox. (The USER/GLOBAL tabs still
# show them as defaults for future code sessions.)
CODE_ONLY: frozenset[str] = frozenset({"permission_mode", "max_turns", "sandbox"})


def is_code_only(key: str) -> bool:
    """Whether ``key`` is a code-session-only setting (menu.md §1.7)."""
    return key in CODE_ONLY


# The order settings appear on a scope page (stable, most-used first). Matches
# menu.md §3.2 Table 10 row order. (#144: "stream_enabled" removed — retired.)
PAGE_ORDER: tuple[str, ...] = (
    "model", "effort", "permission_mode", "max_turns",
    "memory", "sandbox", "language",
)


def role_for(is_owner: bool, level: Optional[str], may_max_effort: bool = False) -> Role:
    """Map the bot's access primitives to a registry ``Role``.

    The owner is always OWNER; an allowlisted ``code`` user is CODE; everyone else
    allowed is CHAT (the middleware already dropped non-allowed users). GUEST is
    only used as the resolver default. ``may_max_effort`` is unused here (effort's
    ``max`` choice is gated separately in the apply path) — kept for call symmetry.
    """
    if is_owner:
        return Role.OWNER
    if level == "code":
        return Role.CODE
    return Role.CHAT


def settings_for_scope(scope: "Scope", role: Role) -> list["Setting"]:
    """The Settings VISIBLE to ``role`` at ``scope``, in PAGE_ORDER.

    A setting shows on a scope tab iff it both (a) declares that scope in its
    ``scopes`` and (b) is viewable by the role (``view_role`` gate). This is the
    single source for what a given user sees — the GLOBAL tab and the owner-only
    rows (sandbox, global model) simply never pass the gate for a non-owner.
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
    """Build a resolution context. ``user_defaults`` (optional) is a preloaded
    {key: value} dict feeding the synchronous USER-scope getters. ``access_base``
    (owner's per-option BASE overrides) and ``access_exceptions`` (this user's
    per-option exceptions) feed the synchronous access resolver (#151)."""
    ctx = Ctx(state=state, user_id=user_id, role=role, settings=settings,
              allowlist=allowlist)
    # Attach the optional preloaded user-defaults for the synchronous USER getters.
    ctx.user_defaults = user_defaults if isinstance(user_defaults, dict) else {}
    # #151: preloaded access config (owner base overrides + this user's exceptions).
    ctx.access_base = access_base if isinstance(access_base, dict) else {}
    ctx.access_exceptions = access_exceptions if isinstance(access_exceptions, dict) else {}
    return ctx
