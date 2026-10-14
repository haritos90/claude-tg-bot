"""Telegram control surface: commands, text routing, permission callbacks.

- updates arrive pre-filtered by the access middleware
- a topic is keyed by `message_thread_id`; General is 0
- the live mode is DM sessions with negative keys
- the supergroup topics path is dormant
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from datetime import datetime, timezone  # CLI last-check timezone

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest  # detect "not modified" on rich edits
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.storage import archive
from app.telegram import commands
from app.storage import db
from app.core import engine
from app import i18n
from app.telegram import markup
from app.telegram import streamer as streamer_mod  # custom-emoji premium gate
from app.core import schedules
from app.core import sessions as _sessions
from app.core import transcribe  # local speech-to-text for voice notes
from app.access import settings_schema as ss
from app.storage import usage
from app.access.allowlist import normalize_date
from app.telegram.rich_message import EditRichMessage, SendRichMessage  # native rich messages
from app.core import models  # model catalog from the CLI
from app.core import cli_update  # CLI version and update checks

log = logging.getLogger("handlers")


# Session type is fixed at creation.
VALID_MODES = ("chat", "code")

# Effort levels come from the CLI per model.
# - only `max` is special, as a per-user permission



def _effort_label(level: str | None, lang: str) -> str:
    """Display name of an effort level, localized when known.

    - `None` gives the localized default label
    """
    if not level:
        return i18n.t("settings.val_default", lang)
    return i18n.maybe_t(f"effort.level.{level}", lang, level)


def _effort_default_label(model: str | None, lang: str) -> str:
    """The default choice of the effort picker.

    - names the model's CLI default level when reported
    """
    dflt = models.default_effort(model) if model else None
    if dflt:
        return i18n.t("effort.default_label", lang, level=_effort_label(dflt, lang))
    return i18n.t("settings.val_default", lang)


def mode_glyph(mode: str) -> str:
    """Visual marker for a session type, shown everywhere.

    - code is a green square, chat a speech bubble
    """
    return "🟩" if mode == "code" else "💬"


def mode_tagline(mode: str, cwd: str | None = None, lang: str = "en") -> str:
    """One-line HTML description of what a session type does."""
    if mode == "code":
        # The workdir path is not shown in session descriptions.
        # - `cwd` stays in the signature for callers
        where = ""
        return i18n.t("mode.tagline_code", lang, glyph=mode_glyph("code"), where=where)
    return i18n.t("mode.tagline_chat", lang, glyph=mode_glyph("chat"))

# Valid usage display modes.
VALID_USAGE_MODES = ("off", "footer", "pinned", "both")

# Accepted image media types for content blocks.
# - photos are always JPEG; file images carry their mime
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Raw-size caps before base64.
# - about 5 MB per image, 32 MB request for PDFs
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 1 * 1024 * 1024
# Raw-size cap for a voice note.
# - the real gate is the duration limit
# - this stops a huge forwarded audio from OOMing decode
MAX_VOICE_BYTES = 20 * 1024 * 1024
# Character cap for inlined text files, protecting the context window.
MAX_TEXT_INLINE_CHARS = 200_000

# Album buffering: items sharing a `media_group_id` become one turn.
# - the debounce window restarts on each arriving item
# - inline text is capped at `MAX_TEXT_INLINE_CHARS`
# - item count is capped at `MAX_ALBUM_ITEMS`, with a dropped note
ALBUM_DEBOUNCE_SECS = 0.8
MAX_ALBUM_ITEMS = 20


def _combine_album_parts(parts, header, truncated_label):
    """Combine buffered album items into one turn's text and blocks.

    - `parts` is a list of `(message_id, {blocks, inline})`
    - items are ordered by message id
    - image and PDF blocks are concatenated
    - inline text is joined under `header`, cut at the cap
    - returns `(text, blocks)`; the caller adds dropped-item notes
    """
    blocks: list = []
    inlines: list[str] = []
    for _mid, part in sorted(parts, key=lambda p: p[0]):
        if part.get("blocks"):
            blocks.extend(part["blocks"])
        if part.get("inline"):
            inlines.append(part["inline"])
    combined = "\n\n".join(inlines)
    if len(combined) > MAX_TEXT_INLINE_CHARS:
        combined = combined[:MAX_TEXT_INLINE_CHARS] + f"\n\n{truncated_label}"
    text = f"{header}\n\n{combined}" if combined else header
    return text, blocks

# Friendly permission names map to SDK `permission_mode` values.
# - help text lives in the l10n table under `perm.help.<name>`
PERM_NAME_TO_MODE: dict[str, str] = {
    "auto-edits": "acceptEdits",
    "plan": "plan",
    "full-access": "bypassPermissions",
}
PERM_MODE_TO_NAME: dict[str, str] = {v: k for k, v in PERM_NAME_TO_MODE.items()}


# Commands advertised to Telegram, derived from the registry.
# - ordered most-used first
# - lists derive from `commands.py` registry, so they can't drift
# - descriptions come from `Cmd.label[lang]`
_COMMAND_NAMES: list[str] = commands.menu_slugs()
_OWNER_COMMAND_NAMES: list[str] = commands.owner_slugs()
_CODE_COMMAND_NAMES: list[str] = commands.code_slugs()


def _chat_command_names() -> list[str]:
    """Command set a chat-level user sees."""
    return [n for n in _COMMAND_NAMES if n not in _CODE_COMMAND_NAMES]


def _chat_menu_names() -> list[str]:
    """Short slash menu for chat-level users: the everyday trio.

    - code users and the owner keep the full set
    """
    return _chat_command_names()[:3]


def _build_commands(names: list[str], lang: str) -> list[BotCommand]:
    """Build a `BotCommand` list with descriptions in one locale.

    - labels come from the `COMMANDS` registry
    - falls back to English when the locale is absent
    """
    by = commands.by_slug()
    out: list[BotCommand] = []
    for name in names:
        cmd = by.get(name)
        desc = cmd.label.get(lang) or cmd.label["en"] if cmd else name
        out.append(BotCommand(command=name, description=desc))
    return out


async def setup_commands(bot, owner_id: int | None = None) -> None:
    """Register the command list with Telegram per locale.

    - one `setMyCommands` call per supported `language_code`
    - the owner's private chat also gets admin commands
    - a scoped list replaces the default, so send it combined
    """
    # Fail loudly if command registry drifts from handlers or locales.
    commands.assert_commands_consistent(languages=tuple(i18n.LANGUAGES))
    # Default scope: chat-level users get only everyday commands.
    # - code-only commands are omitted
    # - code users get full menu on first contact
    # - owner's private chat overrides with the full set
    chat_names = _chat_menu_names()
    await bot.set_my_commands(_build_commands(chat_names, i18n.DEFAULT_LANG))
    for lang in i18n.LANGUAGES:
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                _build_commands(chat_names, lang), language_code=lang
            )
    if owner_id:
        owner_names = _COMMAND_NAMES + _OWNER_COMMAND_NAMES
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                _build_commands(owner_names, i18n.DEFAULT_LANG),
                scope=BotCommandScopeChat(chat_id=owner_id),
            )
        for lang in i18n.LANGUAGES:
            with contextlib.suppress(Exception):
                await bot.set_my_commands(
                    _build_commands(owner_names, lang),
                    scope=BotCommandScopeChat(chat_id=owner_id),
                    language_code=lang,
                )


def thread_key(message: Message) -> int:
    """Return the isolation key: thread id, or 0."""
    return message.message_thread_id or 0


def build_router(settings, sessions, gate, bot, allowlist) -> Router:
    """Build the aiogram Router wiring commands, text, and callbacks.

    - `settings`, `sessions`, `gate`, `bot`, `allowlist` are the shared services
    """
    router = Router(name="main")

    async def reply(message: Message, text: str, reply_markup=None) -> None:
        """Send already-built Telegram HTML into the same topic.

        - sent as-is; running `md_to_html` would double-escape the tags
        - long text is split; very long becomes a .md document
        - `reply_markup` attaches an optional inline keyboard
        """
        # Reply where the message came from.
        # - supergroup topic keeps its thread id; DM has none
        # - use message context, not session key (synthetic in DMs)
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id

        # Send replies as native rich messages for consistent look.
        # - `text` is already HTML; no char-splitting needed
        # - fall back to document/chunked path on failure
        try:
            await bot(SendRichMessage(chat_id=message.chat.id,
                                      rich_message={"html": text},
                                      reply_markup=reply_markup, **send_kwargs))
            return
        except Exception:
            pass

        # Very long text goes out as a document.
        if markup.should_send_as_file(text):
            try:
                document = markup.as_document(text, "message.md")
                await bot.send_document(
                    chat_id=message.chat.id,
                    document=document,
                    **send_kwargs,
                )
                return
            except Exception:
                # Fall through to chunked text if document fails.
                pass

        # Send `text` as-is, splitting only past the size limit.
        _kb_pending = reply_markup  # first chunk only
        for chunk in markup.split_message(text):
            if not chunk:
                continue
            _kb, _kb_pending = _kb_pending, None
            try:
                await bot.send_message(
                    chat_id=message.chat.id,
                    text=chunk,
                    parse_mode="HTML",
                    reply_markup=_kb,
                    **send_kwargs,
                )
            except Exception:
                # Last resort: send fully-escaped plain text.
                try:
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=markup.escape_html(chunk),
                        parse_mode="HTML",
                        **send_kwargs,
                    )
                except Exception:
                    pass

    # ---- helpers ----

    async def reply_rich_html(message: Message, html: str) -> None:
        """Send a read-only reply as a native rich message.

        - falls back to a classic HTML reply on failure
        """
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        # Rich HTML folds raw newlines; convert them to `<br>`.
        # - assumes no `<pre>` blocks in the content
        # - classic fallback keeps raw text; `<br>` is ignored there
        rich_html = html.replace("\n", "<br>")
        try:
            await bot(SendRichMessage(chat_id=message.chat.id,
                                      rich_message={"html": rich_html}, **send_kwargs))
        except Exception:
            await reply(message, html)

    async def _send_menu(chat_id: int, text: str, kb=None, **send_kwargs):
        """Open an inline-keyboard menu as a native rich message.

        - `text` is valid Telegram HTML, sent as the `html` field
        - returns the sent Message, or `None` if all sends fail
        """
        # Rich HTML folds raw newlines; convert them to `<br>`.
        # - assumes menu text has no preformatted blocks
        # - classic fallback keeps raw newlines
        rich_html = text.replace("\n", "<br>")
        try:
            return await bot(SendRichMessage(chat_id=chat_id, rich_message={"html": rich_html},
                                             reply_markup=kb, **send_kwargs))
        except Exception:
            pass
        try:
            return await bot.send_message(chat_id, text, parse_mode="HTML",
                                          reply_markup=kb, **send_kwargs)
        except Exception:
            return None

    async def _edit_menu(msg, text: str, kb=None) -> None:
        """Edit a menu in place as a native rich message.

        - an unchanged body ("message is not modified") is a no-op
        - any other failure falls back to the classic `edit_text`
        """
        rich_html = text.replace("\n", "<br>")
        try:
            await bot(EditRichMessage(chat_id=msg.chat.id, message_id=msg.message_id,
                                      rich_message={"html": rich_html}, reply_markup=kb))
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return  # identical content already shown
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)

    async def _session_key(message: Message) -> int:
        """Resolve the session key for an incoming message.

        - supergroup: the forum topic id (0 for General)
        - DM: the user's current session, created on first contact
        - DM keys are negative so they never collide with topics
        """
        if message.chat.type == "private":
            uid = message.chat.id  # same as user id in DMs
            cur = await db.get_dm_current(uid)
            # Heal a missing or dangling current-session pointer.
            # - re-point to most recent DM session, else mint one
            # - else `_ensure_state` would resurrect an empty stale row
            if cur is None or await db.get_thread(cur) is None:
                page, _ = await db.browse_threads(uid, None, limit=8, offset=0)
                cur = next((r["thread_id"] for r in page if r["thread_id"] < 0), None)
                if cur is None:
                    cur = await db.allocate_dm_session(
                        uid, i18n.t("session.first_default", _lang(message)),
                        settings.default_model, str(settings.base_workdir),
                    )
                await db.set_dm_current(uid, cur)
            return cur
        return message.message_thread_id or 0

    async def _callback_key(cb: CallbackQuery) -> int:
        """Resolve the session key a menu tap should act on.

        - in a DM it is the tapper's current session
        """
        msg = cb.message
        if msg is not None and msg.chat.type == "private":
            cur = await db.get_dm_current(cb.from_user.id)
            return cur if cur is not None else 0
        return thread_key(msg) if msg is not None else 0

    @router.callback_query(F.data.startswith("shk:"))
    async def on_shell_key(cb: CallbackQuery) -> None:
        """Interactive-shell keypad callback.

        - a key button sends one keystroke and re-renders the output
        - `more` and `less` flip between primary and extra keys
        """
        msg = cb.message
        if msg is None:
            await cb.answer()
            return
        token = (cb.data or "shk:").split(":", 1)[1]
        if token in ("more", "less"):
            with contextlib.suppress(Exception):
                await msg.edit_reply_markup(reply_markup=_sessions.shell_keypad(more=(token == "more")))
            await cb.answer()
            return
        # Resolve the session key once.
        key = await _callback_key(cb)
        rendered, awaiting = await sessions.shell_key(key, token, _lang(cb))
        if rendered is None:
            await cb.answer()
            return
        kb = _sessions.shell_keypad() if awaiting else None
        with contextlib.suppress(Exception):
            await bot(EditRichMessage(chat_id=msg.chat.id, message_id=msg.message_id,
                                      rich_message={"markdown": rendered}, reply_markup=kb))
        # Keep the tracked keypad message current.
        # - later /shell toggle then edits the right message
        # - clear it once input is no longer awaited
        if awaiting:
            sessions.set_shell_kb(key, msg.chat.id, msg.message_id, rendered)
        else:
            sessions.set_shell_kb(key, None, None)
        await cb.answer()

    def _command_arg(message: Message) -> str:
        """Return the text after the command word, stripped."""
        text = message.text or message.caption or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()

    def _is_owner(message: Message) -> bool:
        """True iff the message comes from the configured owner."""
        return bool(message.from_user) and message.from_user.id == settings.owner_id

    def _has_code_access(uid: int | None, uname: str | None) -> bool:
        """True iff the user may use code-only features.

        - true for the owner or an allowlist level of "code"
        - gates by user level, so a demoted user is blocked
        """
        return uid == settings.owner_id or allowlist.level_of(uid, uname) == "code"

    def _may_max_effort(uid: int | None, uname: str | None) -> bool:
        """Whether this user may select the expensive `max` effort.

        - the owner, unless self-revoked, or an explicitly granted user
        - guests are blocked to protect the shared subscription
        - `max` is the only effort level the bot names itself
        """
        # Owner goes through `allow_max_effort_of` too.
        # - defaults to True, so behaviour is unchanged
        # - owner self-revoke now gates the owner
        return bool(allowlist.allow_max_effort_of(uid, uname))

    def _lang(obj) -> str:
        """Resolve the acting user's interface locale.

        - reads the per-user cache warmed by `LanguageMiddleware`
        - falls back to the default locale
        """
        user = getattr(obj, "from_user", None)
        return i18n.cached_lang(getattr(user, "id", 0) or 0)

    # Users whose command menu was already applied this process.
    # - first contact sets it once per user
    # - avoids calling `setMyCommands` on every message
    _menu_applied: set[int] = set()

    async def _ensure_state(message: Message):
        """Ensure a `ThreadState` row exists for this session; return it.

        - default workdir is `BASE_WORKDIR/<sid>`, isolated per session
        - only fires for a brand-new key such as a topic
        """
        key = await _session_key(message)
        # Workdir is named by public session id, nested as `<sid>/work`.
        default_cwd = str(settings.base_workdir / db.session_pubid(key) / "work")  # ULID directory name
        st = await db.ensure_thread(
            key, message.chat.id, settings.default_model, default_cwd
        )
        # Set the user's command menu on first contact.
        # - once per process per user, in their language
        # - best-effort; /language re-applies it on demand
        if (message.chat.type == "private" and message.from_user
                and message.from_user.id not in _menu_applied):
            _menu_applied.add(message.from_user.id)
            with contextlib.suppress(Exception):
                await _apply_user_menu(message.chat.id, message.from_user.id,
                                       message.from_user.username, _lang(message))
        # Record the owner's Telegram Premium status.
        # - gates custom animated emoji in the thinking tag
        # - owner's premium counts, not the viewer's
        if message.from_user and message.from_user.id == settings.owner_id:
            streamer_mod.set_owner_premium(bool(message.from_user.is_premium))
        return st

    async def _rebuild_session(thread_id: int) -> bool:
        """Ask the session manager to drop the in-memory session.

        - the next message then uses the new settings
        - falls back to a full reset without a helper
        - returns True when deferred because a turn is running
        """
        helper = getattr(sessions, "on_mode_or_model_or_cwd_change", None)
        if callable(helper):
            try:
                return bool(await helper(thread_id))
            except Exception:
                pass
        # Fallback: reset closes the client and drops the record.
        # - next message rebuilds from persisted state
        # - in-memory session id is lost, which is intended
        try:
            await sessions.reset(thread_id)
        except Exception:
            pass
        return False

    # ---- settings ----

    @router.message(Command("tools"))
    async def cmd_tools(message: Message) -> None:
        """Open the per-session Tools page with on/off toggles.

        - chat shows web tools, code shows the full toolset
        - Back returns to the settings hub
        """
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        try:
            state = await db.get_thread(key)
        except Exception:
            state = None
        try:
            await _send_menu(
                message.chat.id, i18n.t("settings.tools_title", lang),
                _ss_tools_keyboard(state, lang),
            )
        except Exception as exc:
            await reply(message, i18n.t("settings.open_error", lang, err=markup.escape_html(str(exc))))

    @router.message(Command("settings"))
    async def cmd_settings(message: Message) -> None:
        """Open the scope-tabbed settings hub for this session.

        - scopes: this session, my defaults, global
        - Tools, Usage, and Users are sub-pages returning to this hub
        """
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else None
        uname = message.from_user.username if message.from_user else None
        try:
            await _send_ss_hub(message.chat.id, key, uid, uname, lang)
        except Exception as exc:
            await reply(
                message,
                i18n.t("settings.open_error", lang, err=markup.escape_html(str(exc))),
            )

    @router.callback_query(F.data.startswith("st:"))
    async def on_settings_cb(cb: CallbackQuery) -> None:
        """Shim for stale `st:` buttons from old messages.

        - `st:close` deletes the menu; anything else opens the hub
        """
        try:
            msg = cb.message
            if msg is None:
                await cb.answer()
                return
            data = cb.data or ""
            verb = data.split(":")[1] if ":" in data else ""
            lang = _lang(cb)
            if verb == "close":
                try:
                    await msg.delete()
                except Exception:
                    with contextlib.suppress(Exception):
                        await msg.edit_text(i18n.t("settings.closed", lang))
                await cb.answer()
                return
            key = await _callback_key(cb)
            uid = cb.from_user.id if cb.from_user else None
            uname = cb.from_user.username if cb.from_user else None
            await _send_ss_hub(msg.chat.id, key, uid, uname, lang, edit_msg=msg)
            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # Generic registry-driven, scope-tabbed settings hub.
    # - reuses resolver and role gate from `settings_schema`
    # - visibility and edit rights decided in one place

    def _role_of(uid: int | None, uname: str | None) -> ss.Role:
        """The acting user's registry role: owner, code, or chat."""
        is_owner = uid is not None and uid == settings.owner_id
        level = None if is_owner else allowlist.level_of(uid, uname)
        return ss.role_for(is_owner, level)

    async def _build_ss_ctx(key: int, uid: int | None, role: ss.Role) -> ss.Ctx:
        """Build a resolution `Ctx` for the bound session.

        - preloads user defaults, locale, and access config
        - keeps `resolve()` and `effective_access()` synchronous
        """
        try:
            state = await db.get_thread(key)
        except Exception:
            state = None
        user_defaults: dict = {}
        if uid is not None:
            for skey in ss.SETTINGS:
                with contextlib.suppress(Exception):
                    user_defaults[skey] = await db.get_user_default(uid, skey)
            # Language lives in its own kv store.
            with contextlib.suppress(Exception):
                lang_pref = await db.get_user_lang(uid)
                if lang_pref is not None:
                    user_defaults["language"] = lang_pref
        # Owner's per-option base-access overrides plus this user's exceptions.
        access_base: dict = {}
        with contextlib.suppress(Exception):
            access_base = await db.get_access_overrides()
        access_exceptions: dict = {}
        if uid is not None:
            with contextlib.suppress(Exception):
                access_exceptions = allowlist.access_of(uid, None)
        return ss.make_ctx(state=state, user_id=uid, role=role,
                           settings=settings, allowlist=allowlist,
                           user_defaults=user_defaults, access_base=access_base,
                           access_exceptions=access_exceptions)

    def _visible_tabs(role: ss.Role) -> list:
        """Scope tabs this role may see.

        - non-owners never get the Global tab
        """
        tabs = [ss.Scope.SESSION, ss.Scope.USER]
        if role >= ss.Role.OWNER:
            tabs.append(ss.Scope.GLOBAL)
        return tabs

    def _ss_text(scope, role: ss.Role, lang: str) -> str:
        """Header for the active scope tab."""
        return i18n.t("settings.v2_header", lang,
                      tab=i18n.t(_scope_tab_key(scope), lang))

    def _ss_code_blocked(setting, scope, ctx: ss.Ctx) -> bool:
        """Hide code-only settings on the session tab for chat sessions.

        - gated on session mode, not the user's level
        """
        if scope != ss.Scope.SESSION or not ss.is_code_only(setting.key):
            return False
        return getattr(ctx.state, "mode", None) != "code"

    def _ss_hub_keyboard(scope, ctx: ss.Ctx, role: ss.Role, lang: str) -> InlineKeyboardMarkup:
        """Tabbed hub keyboard for the active scope.

        - tab row, then one row per visible setting
        - Tools and owner-only Usage and Users rows last, then Close
        - sub-pages are `sx:` namespaced and return to the hub
        """
        B = InlineKeyboardButton
        rows: list[list[InlineKeyboardButton]] = []
        # Tab row, marking the active tab.
        tab_row = []
        for sc in _visible_tabs(role):
            label = i18n.t(_scope_tab_key(sc), lang)
            tab_row.append(B(text=(f"• {label}" if sc == scope else label),
                             callback_data=f"sx:tab:{_SCOPE_CODE[sc]}"))
        rows.append(tab_row)
        # GLOBAL tab is the owner's access-config surface.
        # - lists every registry option, even without global value scope
        # - SESSION and USER list options storable at that scope
        if scope == ss.Scope.GLOBAL:
            setting_list = [ss.SETTINGS[k] for k in ss.PAGE_ORDER
                            if k in ss.SETTINGS and ss.SETTINGS[k].can_view(role)]
        else:
            setting_list = ss.settings_for_scope(scope, role)
        # One row per visible setting at this scope.
        for setting in setting_list:
            # SESSION/USER rows need a setter; GLOBAL is an admin page.
            if scope != ss.Scope.GLOBAL and setting.set.get(scope) is None:
                continue
            # Code-only rows don't appear in chat sessions.
            if _ss_code_blocked(setting, scope, ctx):
                continue
            # Access model: hidden settings are omitted.
            # - read-only shows but can't be changed
            # - delegated is fully editable; owner is always full
            if scope != ss.Scope.GLOBAL and not ss.can_view_setting(setting, ctx):
                continue
            editable = ss.can_edit_setting(setting, ctx)
            # Show the value that belongs to this scope.
            # - SESSION tab shows the effective resolved value
            # - USER/GLOBAL tabs show what that scope contributes
            # - read-only settings show the access-aware global value
            value, src = (ss.resolve_from(setting, ctx, scope) if editable
                          else ss.resolve_effective(setting, ctx))
            name = _setting_name(setting, lang)
            vlabel = _setting_value_label(setting, value, lang,
                                          _scope_model(ctx, scope) if setting.key == "effort" else None)
            badge = _scope_badge(src, lang)
            text = i18n.t("settings.v2_row", lang, name=name, val=vlabel, badge=badge)
            sc_code = _SCOPE_CODE[scope]
            if scope == ss.Scope.GLOBAL:
                # Owner Global tab row opens the option-admin page.
                cb = f"sx:opt:{setting.key}"
            elif not editable:
                cb = f"sx:ro:{setting.key}"           # read-only shows a locked toast
            else:
                # Every editable setting opens a value picker with Back.
                # - a tap never silently flips a value
                cb = f"sx:nav:{sc_code}:{setting.key}"
            rows.append([B(text=text, callback_data=cb)])
        # Bespoke pages are sub-pages linked from the SESSION tab.
        # - Tools is code-only
        # - owner-only Usage and Users rows go last, above Close
        if scope == ss.Scope.SESSION:
            # Code-only rows need a code session and code-level user.
            # - demoted users with code sessions don't see Tools/Secret
            if getattr(ctx.state, "mode", None) == "code" and role >= ss.Role.CODE:
                rows.append([B(text=i18n.t("settings.row_tools", lang), callback_data="sx:tools")])
                rows.append([B(text=i18n.t("settings.row_secret", lang),
                               callback_data="sx:secret")])
            if role >= ss.Role.OWNER:
                rows.append([B(text=i18n.t("settings.row_usage", lang,
                                           val=getattr(sessions, "usage_mode", "footer")),
                               callback_data="sx:usage")])
                rows.append([B(text=i18n.t("settings.row_users", lang), callback_data="sx:users")])
                # Admin sub-page sits last.
                # - archive retention, global toggles, user-management launchers
                rows.append([B(text=i18n.t("settings.row_admin", lang), callback_data="sx:admin")])
        # Also surface the owner Admin sub-page on the GLOBAL tab.
        # - session limit, retention and toggles are account-wide config
        # - same page; controls are not duplicated
        if scope == ss.Scope.GLOBAL and role >= ss.Role.OWNER:
            rows.append([B(text=i18n.t("settings.row_admin", lang), callback_data="sx:admin")])
        rows.append([B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # ---- owner Admin sub-page ----
    # - retention picker choices: (days, i18n key)
    # - 0 means keep forever
    _RETENTION_CHOICES = (
        (30, "admin.ret_1mo"), (90, "admin.ret_3mo"), (180, "admin.ret_6mo"),
        (365, "admin.ret_12mo"), (0, "admin.ret_never"),
    )
    # Idle-to-fresh-session picker choices, in minutes; 0 is off.
    _IDLE_RESET_CHOICES = (0, 15, 30, 60, 120, 240)

    def _idle_reset_min() -> int:
        """Effective global idle-to-fresh-session window in minutes.

        - live value from the session manager, else config default
        - 0 means off
        """
        sec = float(getattr(sessions, "_idle_reset", 0) or 0)
        return int(sec // 60)

    def _idle_reset_label(minutes: int, lang: str) -> str:
        if minutes <= 0:
            return i18n.t("admin.idle_off", lang)
        if minutes % 60 == 0:
            return i18n.t("admin.idle_hours", lang, n=minutes // 60)
        return i18n.t("admin.idle_mins", lang, n=minutes)

    def _ss_idle_keyboard(cur_min: int, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        rows = [
            [B(text=("✓ " if m == cur_min else "") + _idle_reset_label(m, lang),
               callback_data=f"sx:admin:idleset:{m}")]
            for m in _IDLE_RESET_CHOICES
        ]
        rows.append([B(text=i18n.t("settings.back_to", lang), callback_data="sx:admin"),
                     B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # CLI update time picker: off, or every third UTC hour.
    # - any `HH:MM` from `CLI_UPDATE_AT_UTC` is shown as is
    _CLI_UPDATE_TIMES: tuple = (None,) + tuple((h, 0) for h in range(0, 24, 3))

    def _cli_update_label(hm, lang: str) -> str:
        """Format "12:00 UTC", or the localized "off"."""
        if not hm:
            return i18n.t("admin.cli_off", lang)
        return i18n.t("admin.cli_daily", lang, time=_sessions.format_update_time(hm))

    def _cli_update_text(lang: str) -> str:
        """CLI page header: installed version and jail copy if behind.

        - also shows the last check and its outcome
        - then the cadence prompt
        """
        host_v = cli_update.version_of(cli_update.host_cli()) or "?"
        ver = host_v
        if getattr(settings, "sandbox_per_session_uid", False):
            jail_v = cli_update.version_of(cli_update.staged_source())
            if jail_v and jail_v != host_v:
                ver = i18n.t("admin.cli_ver_jail", lang, host=host_v, jail=jail_v)
        last_ts = float(getattr(sessions, "cli_last_check", 0) or 0)
        last = (datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                if last_ts else i18n.t("admin.cli_never", lang))
        lines = [i18n.t("admin.cli_title", lang, ver=markup.escape_html(ver),
                        last=markup.escape_html(last))]
        res = getattr(sessions, "cli_last_result", None)
        if res is not None:
            if not res.ok:
                lines.append(i18n.t("admin.cli_res_failed", lang,
                                    detail=markup.escape_html(res.detail)))
            elif res.changed:
                lines.append(i18n.t("admin.cli_res_updated", lang,
                                    before=res.before or "?", after=res.after))
            else:
                lines.append(i18n.t("admin.cli_res_current", lang, ver=res.after or "?"))
        lines.append("")
        lines.append(i18n.t("admin.cli_pick", lang))
        return "\n".join(lines)

    def _ss_cli_keyboard(cur, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        btns = [B(text=("✓ " if hm == cur else "") + _cli_update_label(hm, lang),
                  callback_data="sx:admin:cliset:" + (f"{hm[0]:02d}{hm[1]:02d}" if hm else "off"))
                for hm in _CLI_UPDATE_TIMES]
        rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
        rows.append([B(text=i18n.t("admin.cli_now", lang), callback_data="sx:admin:clinow")])
        rows.append([B(text=i18n.t("settings.back_to", lang), callback_data="sx:admin"),
                     B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _ss_admin_bool_keyboard(which: str, cur: bool, lang: str) -> InlineKeyboardMarkup:
        """On/Off picker with Back for an Admin boolean.

        - `which` is the toggle key
        """
        B = InlineKeyboardButton
        rows = [[
            B(text=("✓ " if cur else "") + i18n.onoff(True, lang),
              callback_data=f"sx:admin:boolset:{which}:on"),
            B(text=("✓ " if not cur else "") + i18n.onoff(False, lang),
              callback_data=f"sx:admin:boolset:{which}:off"),
        ]]
        rows.append([B(text=i18n.t("settings.back_to", lang), callback_data="sx:admin"),
                     B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _archive_retention_days() -> int:
        """Effective archive retention in days.

        - the owner's runtime value, else the startup default
        - 0 means keep forever
        """
        raw = await db.get_kv("archive_retention_days")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        return max(0, int(getattr(settings, "archive_retention_days", 180) or 0))

    def _retention_label(days: int, lang: str) -> str:
        for d, k in _RETENTION_CHOICES:
            if d == days:
                return i18n.t(k, lang)
        return i18n.t("admin.ret_days", lang, n=days)

    def _ss_retention_keyboard(cur: int, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        rows = [
            [B(text=("✓ " if d == cur else "") + i18n.t(k, lang),
               callback_data=f"sx:admin:rset:{d}")]
            for d, k in _RETENTION_CHOICES
        ]
        rows.append([B(text=i18n.t("settings.back_to", lang), callback_data="sx:admin"),
                     B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _ss_admin_keyboard(lang: str, ret_days: int, cs_on: bool, wp_on: bool,
                           gsl: int = 10, idle_min: int = 30,
                           cli_at=(12, 0)) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        gsl_lbl = "∞" if gsl <= 0 else str(gsl)
        rows = [
            [B(text=i18n.t("admin.retention", lang, val=_retention_label(ret_days, lang)),
               callback_data="sx:admin:ret"),
             B(text=i18n.t("admin.gsl_btn", lang, val=gsl_lbl), callback_data="sx:admin:gsl")],
            [B(text=i18n.t("admin.idle_btn", lang, val=_idle_reset_label(idle_min, lang)),
               callback_data="sx:admin:idle")],
            # CLI daily update time, plus a check-now action.
            [B(text=i18n.t("admin.cli_btn", lang, val=_cli_update_label(cli_at, lang)),
               callback_data="sx:admin:cli")],
            # Open an On/Off picker with Back, not flip in place.
            [B(text=i18n.t("admin.tog_codesplit", lang, val=i18n.onoff(cs_on, lang)),
               callback_data="sx:admin:bool:cs"),
             B(text=i18n.t("admin.tog_workingplate", lang, val=i18n.onoff(wp_on, lang)),
               callback_data="sx:admin:bool:wp")],
            [B(text=i18n.t("admin.btn_allow", lang), callback_data="sx:admin:cmd:allow"),
             B(text=i18n.t("admin.btn_deny", lang), callback_data="sx:admin:cmd:deny")],
            [B(text=i18n.t("admin.btn_level", lang), callback_data="sx:admin:cmd:level"),
             B(text=i18n.t("admin.btn_expire", lang), callback_data="sx:admin:cmd:expire"),
             B(text=i18n.t("admin.btn_limit", lang), callback_data="sx:admin:cmd:limit")],
            [B(text=i18n.t("admin.btn_userstats", lang), callback_data="usr:stats")],
            [B(text=i18n.t("settings.back_to", lang), callback_data="sx:tab:s"),
             B(text=i18n.t("btn.close", lang), callback_data="sx:close")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _send_ss_admin(msg, lang: str) -> None:
        """Render (edit in place) the owner Admin sub-page."""
        days = await _archive_retention_days()
        cs = bool(getattr(sessions, "split_code_messages", True))
        wp = bool(getattr(sessions, "working_plate", True))
        gsl = await _global_session_limit()
        idle_min = _idle_reset_min()
        cli_at = getattr(sessions, "cli_update_at", None)
        with contextlib.suppress(Exception):
            await _edit_menu(msg, i18n.t("admin.title", lang),
                             _ss_admin_keyboard(lang, days, cs, wp, gsl, idle_min, cli_at))

    def _scope_model(ctx: ss.Ctx, scope) -> str:
        """Model effective at a settings scope.

        - an effort picker lists that model's CLI levels
        - falls back to the deployment default
        """
        val = None
        with contextlib.suppress(Exception):
            val, _ = ss.resolve_from(ss.SETTINGS["model"], ctx, scope)
        return val or settings.default_model

    def _ss_picker_keyboard(setting, scope, ctx: ss.Ctx, lang: str,
                            may_max: bool = True) -> InlineKeyboardMarkup:
        """Choice picker for one fixed-choice setting at a scope.

        - `may_max` hides the gated `max` effort from other users
        - the apply path still enforces it against forged taps
        """
        B = InlineKeyboardButton
        # Mark the value held at this scope, not resolved.
        value, _ = ss.resolve_from(setting, ctx, scope)
        # Effort lists levels of the model effective at this scope.
        # - model picker falls back before CLI reports a catalog
        scope_model = _scope_model(ctx, scope) if setting.key in ("effort", "model") else None
        cur_label = _setting_value_label(setting, value, lang, scope_model)
        sc_code = _SCOPE_CODE[scope]
        choices = _setting_choice_labels(setting, lang, scope_model)
        if setting.key == "effort" and not may_max:
            choices = [(v, lbl) for v, lbl in choices if v != "max"]
        # Full-access is offered to all code users.
        # - the sandbox confines the blast radius to their session
        btns = [B(text=_mark(label, cur_label),
                  callback_data=f"sx:set:{sc_code}:{setting.key}:{cbval}")
                for cbval, label in choices]
        rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"sx:tab:{sc_code}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _ss_apply(setting, scope, raw_val, ctx: ss.Ctx, role: ss.Role,
                        uid: int | None, uname: str | None, key: int) -> bool:
        """Apply a tap after re-checking role and scope server-side.

        - returns True if the value was written
        - forged owner-only taps are rejected; buttons never authorize
        """
        # 1. Setting must be editable by this user.
        # - role gate and access model must both allow it
        # - blocks forged callbacks for read-only or hidden settings
        if not ss.can_edit_setting(setting, ctx):
            return False
        # 2. GLOBAL scope is owner-only regardless of `edit_role`.
        if scope == ss.Scope.GLOBAL and role < ss.Role.OWNER:
            return False
        # 3. There must be a setter for this scope.
        setter = setting.set.get(scope)
        if setter is None:
            return False
        # 4. Per-setting extra gates the role matrix doesn't cover.
        if setting.key == "effort" and raw_val == "max" and not _may_max_effort(uid, uname):
            return False
        # Accept only models the CLI offers, or a family alias.
        # - a forged tap can't store an arbitrary string
        if setting.key == "model" and not models.is_selectable(raw_val):
            return False
        # Effort must be a CLI-listed level; default clears it.
        # - nothing to check before the CLI reports a catalog
        if (setting.key == "effort" and raw_val not in ("default", "none", "reset")
                and models.entries() and raw_val not in models.all_effort_levels()):
            return False
        # 5. Coerce the callback string into the stored value.
        value = _coerce_ss_value(setting, raw_val)
        # Setters may be sync or async.
        # - await only when the call returned an awaitable
        result = setter(ctx, value)
        if inspect.isawaitable(result):
            await result
        # Language has side effects: locale cache and per-chat menu.
        # - model/effort changes need the live SDK client rebuilt
        if setting.key == "language" and value:
            i18n.remember_lang(uid, value)
            with contextlib.suppress(Exception):
                await _apply_user_menu(uid, uid, uname, value)
        elif scope == ss.Scope.SESSION:
            await _rebuild_session(key)
        return True

    def _coerce_ss_value(setting, raw_val):
        """Map a picker callback token to the stored value."""
        if setting.type is bool:
            return raw_val if isinstance(raw_val, bool) else (raw_val == "on")
        if setting.key == "model":
            # Store the catalog value itself, an alias or pinned id.
            # - the CLI resolves an alias to the newest model
            return models.match(raw_val) or raw_val
        if setting.key == "permission_mode":
            return PERM_NAME_TO_MODE.get(raw_val, raw_val)
        if setting.key == "effort":
            return None if raw_val in ("default", "none", "reset") else raw_val
        if setting.key == "max_turns":
            if raw_val in ("default", "none", "off", "0", "unlimited"):
                return None
            try:
                return int(raw_val)
            except (TypeError, ValueError):
                return None
        return raw_val

    async def _send_ss_hub(chat_id: int, key: int, uid: int | None, uname: str | None,
                           lang: str, scope=ss.Scope.SESSION, edit_msg=None) -> None:
        """Render (or re-render) the tabbed hub at `scope`."""
        role = _role_of(uid, uname)
        if scope not in _visible_tabs(role):
            scope = ss.Scope.SESSION  # bounce forged Global tab to session
        ctx = await _build_ss_ctx(key, uid, role)
        text = _ss_text(scope, role, lang)
        kb = _ss_hub_keyboard(scope, ctx, role, lang)
        if edit_msg is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(edit_msg, text, kb)
            return
        await _send_menu(chat_id, text, kb)

    async def _send_setting_picker(chat_id: int, key: int, uid: int | None,
                                   uname: str | None, lang: str, setting_key: str,
                                   scope=ss.Scope.SESSION) -> bool:
        """Open the hub picker for one setting as a message.

        - slash commands share this one code path with the hub
        - returns False if not viewable or code-only here
        """
        role = _role_of(uid, uname)
        setting = ss.SETTINGS.get(setting_key)
        if setting is None or not setting.can_view(role):
            return False
        if scope not in setting.scopes:
            scope = setting.scopes[0]
        ctx = await _build_ss_ctx(key, uid, role)
        if _ss_code_blocked(setting, scope, ctx):
            return False
        kb = _ss_picker_keyboard(setting, scope, ctx, lang,
                                 may_max=_may_max_effort(uid, uname))
        with contextlib.suppress(Exception):
            await _send_menu(
                chat_id,
                i18n.t("settings.v2_pick", lang, name=_setting_name(setting, lang)),
                kb)
        return True

    @router.callback_query(F.data.startswith("sx:"))
    async def on_settings_v2_cb(cb: CallbackQuery) -> None:
        """Drive the settings hub: tab switch, picker, apply."""
        try:
            parts = (cb.data or "").split(":")
            verb = parts[1] if len(parts) > 1 else ""
            msg = cb.message
            if msg is None:
                await cb.answer()
                return
            key = await _callback_key(cb)
            lang = _lang(cb)
            uid = cb.from_user.id if cb.from_user else None
            uname = cb.from_user.username if cb.from_user else None
            role = _role_of(uid, uname)

            if verb == "close":
                try:
                    await msg.delete()
                except Exception:
                    with contextlib.suppress(Exception):
                        await msg.edit_text(i18n.t("settings.closed", lang))
                await cb.answer()
                return

            if verb == "tab":
                scope = _CODE_SCOPE.get(parts[2] if len(parts) > 2 else "s", ss.Scope.SESSION)
                await _send_ss_hub(msg.chat.id, key, uid, uname, lang, scope, edit_msg=msg)
                await cb.answer()
                return

            if verb == "secret":
                # Open the `/secret` arg-capture prompt from the hub.
                # - Session tab, code only; makes it discoverable
                ctx = await _build_ss_ctx(key, uid, role)
                if getattr(ctx.state, "mode", None) != "code" or not _has_code_access(uid, uname):
                    await cb.answer(i18n.t("common.error", lang))  # level gate too
                    return
                secrets = _read_secrets(key)
                names = (", ".join(f"<code>{markup.escape_html(n)}</code>" for n in secrets)
                         or i18n.t("secret.none", lang))
                pending[(msg.chat.id, thread_key(msg), uid or 0)] = "secret"
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text=i18n.t("secret.btn_guide", lang), callback_data="secret:guide")]])
                await _send_menu(msg.chat.id, i18n.t("secret.help", lang, names=names), kb)
                await cb.answer()
                return

            if verb == "nav" and len(parts) >= 4:
                scope = _CODE_SCOPE.get(parts[2], ss.Scope.SESSION)
                setting = ss.SETTINGS.get(parts[3])
                # Gate: must be viewable; Global tab is owner-only.
                if (setting is None or not setting.can_view(role)
                        or (scope == ss.Scope.GLOBAL and role < ss.Role.OWNER)):
                    await cb.answer(i18n.t("common.error", lang))
                    return
                ctx = await _build_ss_ctx(key, uid, role)
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("settings.v2_pick", lang, name=_setting_name(setting, lang)),
                        _ss_picker_keyboard(
                            setting, scope, ctx, lang, may_max=_may_max_effort(uid, uname)))
                await cb.answer()
                return

            if verb in ("set", "tog") and len(parts) >= 4:
                scope = _CODE_SCOPE.get(parts[2], ss.Scope.SESSION)
                setting = ss.SETTINGS.get(parts[3])
                if setting is None:
                    await cb.answer(i18n.t("common.error", lang))
                    return
                ctx = await _build_ss_ctx(key, uid, role)
                if verb == "tog":
                    # Flip the value held at this scope.
                    # - avoids inverting a session override into user defaults
                    value, _ = ss.resolve_from(setting, ctx, scope)
                    raw_val = not bool(value)  # flip the scope-local bool
                else:
                    raw_val = parts[4] if len(parts) > 4 else ""
                ok = await _ss_apply(setting, scope, raw_val, ctx, role, uid, uname, key)
                if not ok:
                    # Forged or unauthorized tap, or a gated choice.
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                lang = _lang(cb)  # updates the acting locale
                await _send_ss_hub(msg.chat.id, key, uid, uname, lang, scope, edit_msg=msg)
                await cb.answer(i18n.t("settings.saved", lang))
                return

            # ---- bespoke sx: sub-pages ----
            if verb == "tools":
                # Per-session Tools grid, code-only; render in place.
                state = None
                with contextlib.suppress(Exception):
                    state = await db.get_thread(key)
                if getattr(state, "mode", None) != "code" or not _has_code_access(uid, uname):
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, i18n.t("settings.tools_title", lang),
                                     _ss_tools_keyboard(state, lang))
                await cb.answer()
                return

            if verb == "tooltog" and len(parts) >= 3:
                tool = parts[2]
                state = None
                with contextlib.suppress(Exception):
                    state = await db.get_thread(key)
                mode = getattr(state, "mode", "chat")
                universe = engine.CODE_TOOLS if mode == "code" else engine.CHAT_TOOLS
                if mode == "code" and tool in universe and _has_code_access(uid, uname):
                    base = (state.tools_enabled if state and state.tools_enabled is not None
                            else list(universe))
                    enabled = {t for t in base if t in universe}
                    enabled.discard(tool) if tool in enabled else enabled.add(tool)
                    ordered = [t for t in universe if t in enabled]
                    # None means the whole tool universe is on.
                    # - tools added later default on
                    await db.set_tools_enabled(
                        key, None if set(ordered) == set(universe) else ordered)
                    await _rebuild_session(key)
                    state = await db.get_thread(key)
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, i18n.t("settings.tools_title", lang),
                                         _ss_tools_keyboard(state, lang))
                await cb.answer()
                return

            if verb == "users":
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer()
                return

            if verb == "usage":
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("settings.v2_pick", lang, name=i18n.t("settings.usage_name", lang)),
                        _ss_usage_keyboard(getattr(sessions, "usage_mode", "footer"), lang))
                await cb.answer()
                return

            if verb == "usageset" and len(parts) >= 3:
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                mode_val = parts[2]
                if mode_val in ("off", "footer", "pinned", "both"):
                    with contextlib.suppress(Exception):
                        await sessions.set_usage_mode(mode_val)
                await _send_ss_hub(msg.chat.id, key, uid, uname, lang, ss.Scope.SESSION, edit_msg=msg)
                await cb.answer(i18n.t("settings.saved", lang))
                return

            # ---- owner Admin sub-page ----
            if verb == "admin":
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                sub = parts[2] if len(parts) > 2 else ""
                arg = parts[3] if len(parts) > 3 else ""
                if sub == "ret":
                    # Open the archive-retention picker.
                    cur = await _archive_retention_days()
                    with contextlib.suppress(Exception):
                        await _edit_menu(
                            msg, i18n.t("admin.retention_title", lang),
                            _ss_retention_keyboard(cur, lang))
                    await cb.answer()
                    return
                if sub == "rset":
                    try:
                        days = max(0, int(arg))
                    except (TypeError, ValueError):
                        days = 180
                    await db.set_kv("archive_retention_days", str(days))
                    await _send_ss_admin(msg, lang)
                    await cb.answer(i18n.t("admin.ret_saved", lang, val=_retention_label(days, lang)))
                    return
                if sub == "idle":
                    # Open the idle-to-fresh-session picker.
                    with contextlib.suppress(Exception):
                        await _edit_menu(
                            msg, i18n.t("admin.idle_title", lang),
                            _ss_idle_keyboard(_idle_reset_min(), lang))
                    await cb.answer()
                    return
                if sub == "cli":
                    # Open the CLI auto-update page.
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, _cli_update_text(lang),
                                         _ss_cli_keyboard(sessions.cli_update_at, lang))
                    await cb.answer()
                    return
                if sub == "cliset":
                    # Arg is `HHMM` in UTC, or `off`.
                    raw = str(arg or "")
                    hm = (_sessions.parse_update_time(f"{raw[:2]}:{raw[2:]}")
                          if len(raw) == 4 and raw.isdigit() else None)
                    await sessions.set_cli_update_at(hm)
                    await _send_ss_admin(msg, lang)
                    await cb.answer(
                        i18n.t("admin.cli_saved", lang, val=_cli_update_label(hm, lang)))
                    return
                if sub == "clinow":
                    # Run one update round now; page re-renders with the outcome.
                    await cb.answer(i18n.t("admin.cli_checking", lang))
                    with contextlib.suppress(Exception):
                        await sessions.update_cli_now()
                    with contextlib.suppress(Exception):
                        await sessions.probe_models()  # new CLI refreshes the model list
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, _cli_update_text(lang),
                                         _ss_cli_keyboard(sessions.cli_update_at, lang))
                    return
                if sub == "idleset":
                    try:
                        mins = max(0, int(arg))
                    except (TypeError, ValueError):
                        mins = 30
                    await sessions.set_idle_reset_sec(mins * 60)
                    await _send_ss_admin(msg, lang)
                    await cb.answer(
                        i18n.t("admin.idle_saved", lang, val=_idle_reset_label(mins, lang)))
                    return
                if sub == "gsl":
                    # Global per-user session limit: capture the owner's next message.
                    # - a number, or off/unlimited; handled by `_run_pending`
                    pending[(msg.chat.id, thread_key(msg), uid or 0)] = "gsessionlimit"
                    with contextlib.suppress(Exception):
                        await bot.send_message(msg.chat.id, i18n.t("admin.gsl_prompt", lang),
                                               parse_mode="HTML")
                    await cb.answer()
                    return
                if sub == "cmd" and arg in ("allow", "deny", "level", "expire", "limit"):
                    # Launch an owner arg-capture command from the Admin page.
                    # - set up pending capture and send the command's prompt
                    # - next owner message goes through `_run_pending`
                    pending[(msg.chat.id, thread_key(msg), uid or 0)] = arg
                    with contextlib.suppress(Exception):
                        await bot.send_message(msg.chat.id, i18n.t(f"{arg}.prompt", lang),
                                               parse_mode="HTML")
                    await cb.answer()
                    return
                if sub == "bool" and arg in ("cs", "wp"):
                    # Open On/Off picker for global owner toggles.
                    # - code-block split, working plate
                    cur = (bool(getattr(sessions, "split_code_messages", True)) if arg == "cs"
                           else bool(getattr(sessions, "working_plate", True)))
                    name = i18n.t("admin.name_codesplit" if arg == "cs"
                                  else "admin.name_workingplate", lang)
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, i18n.t("settings.v2_pick", lang, name=name),
                                         _ss_admin_bool_keyboard(arg, cur, lang))
                    await cb.answer()
                    return
                if sub == "boolset" and arg in ("cs", "wp"):
                    val = (parts[4] if len(parts) > 4 else "") == "on"
                    if arg == "cs":
                        await sessions.set_split_code_messages(val)
                    else:
                        await sessions.set_working_plate(val)
                    await _send_ss_admin(msg, lang)
                    await cb.answer(i18n.t("settings.saved", lang))
                    return
                # Default: render the Admin page.
                await _send_ss_admin(msg, lang)
                await cb.answer()
                return

            # ---- access model: read-only toast, option-admin pages ----
            if verb == "ro":
                # A read-only row was tapped; explain it isn't delegated.
                await cb.answer(i18n.t("settings.ro_toast", lang), show_alert=True)
                return

            if verb == "opt" and len(parts) >= 3:
                # Owner option-admin page: global value and base access.
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                setting = ss.SETTINGS.get(parts[2])
                if setting is None:
                    await cb.answer(i18n.t("common.error", lang))
                    return
                octx = await _build_ss_ctx(key, uid, role)
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("settings.opt_title", lang, name=_setting_name(setting, lang)),
                        _ss_option_admin_kb(setting, octx, lang))
                await cb.answer()
                return

            if verb == "acc" and len(parts) >= 3:
                # Base-access picker for one option (owner).
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                setting = ss.SETTINGS.get(parts[2])
                if setting is None:
                    await cb.answer(i18n.t("common.error", lang))
                    return
                octx = await _build_ss_ctx(key, uid, role)
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("settings.acc_title", lang, name=_setting_name(setting, lang)),
                        _ss_access_kb(setting, octx, lang))
                await cb.answer()
                return

            if verb == "accset" and len(parts) >= 4:
                # Apply a base-access change, then re-render the option-admin page.
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                okey, level = parts[2], parts[3]
                if okey in ss.SETTINGS and level in ("hidden", "readonly", "delegated"):
                    with contextlib.suppress(Exception):
                        await db.set_access_override(okey, level)
                setting = ss.SETTINGS.get(okey)
                octx = await _build_ss_ctx(key, uid, role)
                if setting is not None:
                    with contextlib.suppress(Exception):
                        await _edit_menu(
                            msg,
                            i18n.t("settings.opt_title", lang, name=_setting_name(setting, lang)),
                            _ss_option_admin_kb(setting, octx, lang))
                await cb.answer(i18n.t("settings.saved", lang))
                return

            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ---- language ----

    def _language_keyboard(current: str) -> InlineKeyboardMarkup:
        """Inline picker listing every supported locale."""
        rows = [
            [InlineKeyboardButton(
                text=_mark(i18n.lang_name(code), i18n.lang_name(current)),
                callback_data=f"lang:set:{code}")]
            for code in i18n.LANGUAGES
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _apply_user_menu(chat_id: int, uid: int, uname: str | None, lang: str) -> None:
        """Set the user's per-chat command menu language and access level.

        - overrides Telegram's client-language default
        - chat-level users never see code commands; DM only
        """
        is_owner = uid == settings.owner_id
        level = "code" if is_owner else (allowlist.level_of(uid, uname) or "chat")
        # Chat users get the short menu; code users full.
        names = list(_COMMAND_NAMES) if level == "code" else _chat_menu_names()
        if is_owner:
            names = names + _OWNER_COMMAND_NAMES
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                _build_commands(names, lang),
                scope=BotCommandScopeChat(chat_id=chat_id),
            )

    @router.message(Command("language"))
    async def cmd_language(message: Message) -> None:
        """Show the language picker, or set it directly."""
        await _ensure_state(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        arg = _command_arg(message).strip().lower()
        if arg:
            base = arg.split("-", 1)[0]
            if base in i18n.LANGUAGES:
                await db.set_user_lang(uid, base)
                i18n.remember_lang(uid, base)
                # Refresh the command menu in the chosen language.
                # - per-chat scope overrides Telegram's client-language default
                if message.chat.type == "private":
                    uname = message.from_user.username if message.from_user else None
                    await _apply_user_menu(message.chat.id, uid, uname, base)
                await reply(message, i18n.t("lang.set", base, name=i18n.lang_name(base)))
                return
            # Unknown value: fall through to the picker.
        # No or invalid arg: show the unified hub picker.
        # - USER scope; one code path per setting
        key = await _session_key(message)
        uname = message.from_user.username if message.from_user else None
        if await _send_setting_picker(message.chat.id, key, uid, uname, lang,
                                      "language", ss.Scope.USER):
            return
        with contextlib.suppress(Exception):
            await _send_menu(
                message.chat.id,
                i18n.t("lang.title", lang, name=i18n.lang_name(lang)),
                _language_keyboard(lang),
            )

    @router.callback_query(F.data.startswith("lang:"))
    async def on_language_cb(cb: CallbackQuery) -> None:
        """Apply a tap on the language picker."""
        try:
            parts = (cb.data or "").split(":")
            code = parts[2] if len(parts) > 2 else ""
            if code in i18n.LANGUAGES and cb.from_user is not None:
                await db.set_user_lang(cb.from_user.id, code)
                i18n.remember_lang(cb.from_user.id, code)
                if cb.message is not None and cb.message.chat.type == "private":
                    await _apply_user_menu(cb.message.chat.id, cb.from_user.id,
                                           cb.from_user.username, code)
            lang = _lang(cb)
            if cb.message is not None:
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        cb.message,
                        i18n.t("lang.set", lang, name=i18n.lang_name(lang)),
                    )
            await cb.answer(i18n.t("common.switched", lang))
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ---- arg capture ----
    # - commands needing free text prompt, then capture next message
    # - keyed by (chat, thread, user)
    # - consumed by next plain message or cleared by /cancel
    pending: dict[tuple, str] = {}

    # Per-uid lock serializing idle rotation.
    # - stops two near-simultaneous DMs both minting a fresh session
    # - TOCTOU between `get_thread` and `_new_dm_session`
    rotate_locks: dict[int, asyncio.Lock] = {}

    # Media-group (album) coalescing buffer.
    # - keyed by (chat_id, thread_key, media_group_id)
    # - value: parts, caption, msg, lang, timer, dropped
    # - filled by attachment handlers, flushed by `_flush_album`
    album_buf: dict[tuple, dict] = {}

    def _pkey(message: Message) -> tuple:
        uid = message.from_user.id if message.from_user else 0
        return (message.chat.id, thread_key(message), uid)

    def _parse_new(arg: str) -> tuple[str, str]:
        """Parse `[chat|code] <name>` into `(mode, name)`.

        - no type prefix means chat
        """
        parts = arg.strip().split(maxsplit=1)
        if parts and parts[0].lower() in VALID_MODES:
            return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        return "chat", arg.strip()

    async def _new_dm_session(uid: int, mode: str, name: str) -> int:
        """Create a typed DM session, switch to it, return key."""
        key = await db.allocate_dm_session(
            uid, name, settings.default_model, str(settings.base_workdir), mode=mode
        )
        await db.set_dm_current(uid, key)
        return key

    async def _global_session_limit() -> int:
        """Global default per-user session limit.

        - owner-set value, else the config default
        - 0 means unlimited
        """
        raw = await db.get_kv("max_sessions_default")
        default = getattr(settings, "max_sessions_default", 500)
        try:
            return max(0, int(raw)) if raw is not None else default
        except (TypeError, ValueError):
            return default

    async def _effective_max_sessions(uid: int, uname: str | None) -> int:
        """Resolve a user's session-count cap.

        - order: per-user override, owner uncapped, global default
        - 0 means unlimited
        """
        override = allowlist.max_sessions_of(uid, uname)
        if override is not None:
            return override
        if uid == settings.owner_id:
            return 0  # owner uncapped by default; per-user settable
        return await _global_session_limit()

    async def _session_limit_block(uid: int, uname: str | None, lang: str) -> str | None:
        """Return the block message at the session cap, else `None`.

        - counts all the user's DM sessions, chat and code
        - DM-only: the cap is per-user, keyed by user id
        - forum-topic sessions are keyed by group, outside the cap
        """
        cap = await _effective_max_sessions(uid, uname)
        if cap <= 0:
            return None
        _, total = await db.browse_threads(uid, limit=1)
        if total < cap:
            return None
        return i18n.t("session.limit_reached", lang, cap=cap, total=total)

    def _default_session_name(mode: str, lang: str) -> str:
        """Localized default name for an unnamed session."""
        return i18n.t(
            "session.default_name_code" if mode == "code" else "session.default_name_chat",
            lang,
        )

    async def _session_meta_line(st, lang: str) -> str:
        """Model and effort line for a session.

        - the model's catalog display name and its effort level
        - effort falls back to the model's CLI default
        - effort is omitted for a model that takes none
        """
        model, effort = await sessions.model_and_effort(st)
        # Show the model the session runs as.
        mlabel = markup.escape_html(models.runs_as_label(model))
        if not models.effort_levels(model) and models.entries():
            return i18n.t("session.card_meta_model", lang, model=mlabel)
        return i18n.t("session.card_meta", lang, model=mlabel,
                      effort=markup.escape_html(_effort_label(effort, lang)))

    async def _session_model_line(st, lang: str) -> str:
        """Short "Opus 5.5 · medium" label for a session's model.

        - just the model if it takes no effort
        """
        model, effort = await sessions.model_and_effort(st)
        name = markup.escape_html(models.runs_as_label(model))
        if not effort or (models.entries() and not models.effort_levels(model)):
            return name
        return i18n.t("session.model_line", lang, model=name,
                      effort=markup.escape_html(_effort_label(effort, lang)))

    def _created_text(mode: str, name: str, lang: str, meta: str = "") -> str:
        """Confirmation after creating and switching to a session.

        - leads with the mode glyph and tagline
        - `meta` is the model and effort line
        """
        return i18n.t(
            "session.created",
            lang,
            glyph=mode_glyph(mode),
            name=markup.escape_html(name),
            meta=meta,
            tagline=mode_tagline(mode, lang=lang),
        )

    async def _dispose_session(uid: int, key: int, name: str | None) -> bool:
        """Reset, delete, and archive one session.

        - shared by the cap evictor and the untitled-empty cleanup
        - returns True if the row was deleted
        - the body lives in `SessionManager.dispose_dm_session`
        """
        return await sessions.dispose_dm_session(uid, key, name)

    async def _gc_untitled_empties(uid: int, keep: int) -> int:
        """Keep at most one empty untitled session per user.

        - `keep` (current or target) is exempt
        - a used session still unnamed is auto-named, else archived
        - the CLI writes no title for very short prompts
        - returns the number archived
        """
        try:
            _named, disposed = await sessions.tidy_untitled(uid, keep)
        except Exception:
            return 0
        return disposed

    async def _evict_oldest_empty(uid: int, exclude: int) -> bool:
        """Free one session slot by archiving the oldest disposable session.

        - non-current, non-favorite, with zero usage
        - returns True if one was archived
        - a session with any usage is never auto-deleted
        """
        page, _ = await db.browse_threads(uid, None, limit=100, offset=0)
        cands = []
        for r in page:
            tid = r["thread_id"]
            if tid == exclude or r.get("favorite"):
                continue
            try:
                tot = await db.get_usage_totals(tid)
            except Exception:
                continue
            if int(tot.get("requests", 0) or 0) == 0:
                cands.append(r)
        if not cands:
            return False
        victim = min(cands, key=lambda r: r.get("created_at") or 0)
        # Reset, delete and archive via the shared helper.
        return await _dispose_session(uid, victim["thread_id"], victim.get("name"))

    async def _rotate_if_idle(message: Message) -> tuple[int, bool]:
        """Resolve the current DM session key, rotating when idle.

        - starts a new session when idle past the window
        - returns `(key, rotated)`; DM only, topics never rotate
        - the new session inherits the old one's mode
        - at the cap, archives the oldest disposable empty session
        - with none disposable, resets in place; no content lost
        """
        key = await _session_key(message)
        if message.chat.type != "private":
            return key, False
        uid = message.chat.id
        window = await sessions.idle_reset_seconds(uid)
        if window <= 0:
            return key, False
        # Serialize decide-then-rotate on a per-uid lock.
        # - re-read current key and `last_active` inside the lock
        # - a concurrent message may have rotated or refreshed
        lock = rotate_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            key = await _session_key(message)
            st = await db.get_thread(key)
            # Idle means the user's overall inactivity gap.
            # - not this session's age; old sessions stay
            # - only a gap since last activity rotates
            # - an explicit switch stamps activity too
            user_la = await db.get_user_last_active(uid)
            now = time.time()
            await db.set_user_last_active(uid, now)  # this message is user activity
            if st is None or not st.last_active:
                return key, False  # empty session is already fresh
            if not user_la or (now - user_la) < window:
                return key, False  # active within window: continue session
            lang = _lang(message)
            uname = message.from_user.username if message.from_user else None
            if await _session_limit_block(uid, uname, lang) is not None:
                # At cap: archive an empty session, else reset in place.
                if not await _evict_oldest_empty(uid, exclude=key):
                    with contextlib.suppress(Exception):
                        await sessions.rotate_in_place(key)
                    return key, False
            # Auto-started idle sessions are always chat, never code.
            # - code is privileged and entered only explicitly
            newk = await _new_dm_session(uid, "chat", _default_session_name("chat", lang))
            # Rotation is where leftover unnamed sessions land.
            # - name or archive them now to avoid pile-up
            with contextlib.suppress(Exception):
                await _gc_untitled_empties(uid, newk)
            return newk, True

    async def _session_key_for_turn(message: Message) -> int:
        """Session key for a conversational turn.

        - wraps the idle rotation and drops the rotated flag
        - idle rotation is silent, surfaced only in `/sessions`
        """
        key, _ = await _rotate_if_idle(message)
        return key

    async def _do_new(message: Message, arg: str) -> None:
        # Sessions are born chat; /code and /chat switch later.
        # - explicit code request upgrades only with code access
        lang = _lang(message)
        mode, name = _parse_new(arg)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        can_code = (uid == settings.owner_id) or (allowlist.level_of(uid, uname) == "code")
        want_code = (mode == "code")
        if want_code and not can_code:
            await reply(message, i18n.t("access.code_denied", lang))
            return
        if not name:
            name = _default_session_name("code" if want_code else "chat", lang)
        if message.chat.type == "private":
            block = await _session_limit_block(uid, uname, lang)
            if block:
                await reply(message, block)
                return
            key = await _new_dm_session(message.chat.id, "chat", name)
            if want_code:
                await db.switch_mode(key, "code")
                await _rebuild_session(key)
            final = "code" if want_code else "chat"
            # Name the model and effort the new session runs on.
            meta = ""
            with contextlib.suppress(Exception):
                meta = await _session_model_line(await db.get_thread(key), lang)
            txt = _created_text(final, name, lang, meta or markup.escape_html(name))
            await reply(message, txt)
            return
        # Supergroup support is paused; DM-only for now.
        # - rich-draft streaming fails in supergroups (`TEXTDRAFT_PEER_INVALID`)
        # - reply with a paused notice, not a topic
        # - per-user cap stays DM-only; topics keyed by group chat_id
        await reply(message, i18n.t("topic.disabled", lang))
        return

    async def _do_rename(message: Message, name: str, key: int | None = None) -> None:
        # DM: rename a bot-managed session (given key, else current).
        # - supergroup: rename the topic
        lang = _lang(message)
        if message.chat.type == "private":
            target = key if key is not None else await _session_key(message)
            uid = message.from_user.id if message.from_user else 0
            st = await db.get_thread(target)
            if st is None or (st.chat_id != uid and st.created_by != uid):
                await reply(message, i18n.t("common.error", lang))
                return
            await db.set_session_name(target, name)
            await reply(
                message,
                i18n.t("session.renamed", lang, name=markup.escape_html(name)),
            )
            return
        # Supergroup paused: forum-topic rename disabled, DM-only for now.
        await reply(message, i18n.t("topic.disabled", lang))
        return

    async def _run_pending(action: str, message: Message, text: str) -> None:
        if action == "new":
            await _do_new(message, text)
        elif action == "rename":
            await _do_rename(message, text)
        elif action.startswith("rename:"):
            try:
                rkey = int(action.split(":", 1)[1])
            except ValueError:
                rkey = None
            await _do_rename(message, text, key=rkey)
        elif action == "allow":
            await _do_allow(message, text)
        elif action == "deny":
            await _do_deny(message, text)
        elif action == "whois":
            await _do_whois(message, text)
        elif action == "level":
            await _do_level(message, text)
        elif action == "expire":
            await _do_expire(message, text)
        elif action == "limit":
            await _do_limit(message, text)
        elif action.startswith(("usrexp:", "usrrday:", "usrrweek:", "usrname:", "usridle:", "usrmax:")):
            await _apply_user_value(message, action, text)
        elif action == "gsessionlimit":
            await _set_global_session_limit(message, text)
        elif action == "sessearch":
            await _open_sessions(message, keyword=text)
        elif action == "secret":
            await _do_secret(message, text)
        elif action == "schedule":
            await _do_schedule(message, text)

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message) -> None:
        """Cancel a pending 'command then send the argument' prompt."""
        lang = _lang(message)
        if pending.pop(_pkey(message), None):
            await reply(message, i18n.t("common.cancelled", lang))
        else:
            await reply(message, i18n.t("common.nothing_cancel", lang))

    # ---- recurring schedules ----

    _MAX_SCHEDULES_PER_USER = 5

    def _fmt_when(ts: float | None, lang: str) -> str:
        """Short local-time label for a next-run timestamp."""
        if not ts:
            return "—"
        return datetime.fromtimestamp(ts).strftime("%a %m-%d %H:%M")

    async def _do_schedule(message: Message, text: str) -> None:
        """Parse and persist a `<when> | <prompt>` schedule."""
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        try:
            spec, prompt = schedules.parse_schedule(text)
        except schedules.ScheduleError as exc:
            await reply(message, i18n.t("schedule.parse_error", lang,
                                        err=markup.escape_html(str(exc))))
            return
        if await db.count_schedules(uid) >= _MAX_SCHEDULES_PER_USER:
            await reply(message, i18n.t("schedule.cap_reached", lang,
                                        n=_MAX_SCHEDULES_PER_USER))
            return
        now = time.time()
        nxt = schedules.next_run_after(spec, now)
        thread_id = await _session_key(message)
        await db.add_schedule(thread_id, message.chat.id, uid, json.dumps(spec),
                              prompt, nxt, now)
        await reply(message, i18n.t("schedule.created", lang,
                                    when=markup.escape_html(schedules.describe(spec)),
                                    next=_fmt_when(nxt, lang)))

    @router.message(Command("schedule"))
    async def cmd_schedule(message: Message) -> None:
        """Create a recurring scheduled prompt.

        - with no argument, prompts and captures the next message
        """
        await _ensure_state(message)
        lang = _lang(message)
        arg = _command_arg(message)
        if not arg:
            # One bubble, not two separate replies.
            pending[_pkey(message)] = "schedule"
            await reply(message, i18n.t("schedule.usage", lang) + "\n\n"
                        + i18n.t("schedule.prompt", lang))
            return
        await _do_schedule(message, arg)

    def _schedules_keyboard(rows: list[dict], lang: str) -> InlineKeyboardMarkup | None:
        """Per-schedule pause/resume and delete buttons."""
        kb: list[list[InlineKeyboardButton]] = []
        for r in rows:
            sid = int(r["id"])
            toggle = ("btn.sched_pause" if r["enabled"] else "btn.sched_resume")
            kb.append([
                InlineKeyboardButton(text=i18n.t(toggle, lang), callback_data=f"sch:tog:{sid}"),
                InlineKeyboardButton(text=i18n.t("btn.sched_delete", lang), callback_data=f"sch:del:{sid}"),
            ])
        return InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

    async def _render_schedules(uid: int, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
        rows = await db.list_schedules(uid)
        if not rows:
            return i18n.t("schedule.list_empty", lang), None
        lines = [i18n.t("schedule.list_header", lang, n=len(rows), cap=_MAX_SCHEDULES_PER_USER)]
        for r in rows:
            try:
                spec = json.loads(r["spec"])
                when = schedules.describe(spec)
            except Exception:
                when = "?"
            state = "🟢" if r["enabled"] else "⏸"
            lines.append(i18n.t("schedule.list_item", lang, state=state,
                                when=markup.escape_html(when),
                                next=(_fmt_when(r["next_run"], lang) if r["enabled"] else "—"),
                                prompt=markup.escape_html((r["prompt"] or "")[:80])))
        return "\n".join(lines), _schedules_keyboard(rows, lang)

    @router.message(Command("schedules"))
    async def cmd_schedules(message: Message) -> None:
        """List the user's schedules with pause, resume, and delete controls."""
        await _ensure_state(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        text, kb = await _render_schedules(uid, lang)
        await reply(message, text, reply_markup=kb)

    @router.callback_query(F.data.startswith("sch:"))
    async def on_schedules_cb(cb: CallbackQuery) -> None:
        """Pause, resume, or delete a schedule, then re-render in place."""
        lang = _lang(cb)
        uid = cb.from_user.id if cb.from_user else 0
        try:
            _, verb, sid_s = cb.data.split(":", 2)
            sid = int(sid_s)
        except (ValueError, AttributeError):
            await cb.answer()
            return
        row = await db.get_schedule(sid)
        # Only the schedule's owner may touch it.
        if row is None or int(row["owner_uid"]) != uid:
            await cb.answer(i18n.t("common.error", lang))
            return
        if verb == "del":
            await db.delete_schedule(sid)
            await cb.answer(i18n.t("schedule.deleted", lang))
        elif verb == "tog":
            now_on = not bool(row["enabled"])
            if now_on:
                # Resuming recomputes the next run from now.
                # - avoids firing for every missed slot while paused
                # - enable only if recompute succeeds; bad spec stays paused
                try:
                    spec = json.loads(row["spec"])
                    await db.update_schedule_run(
                        sid, schedules.next_run_after(spec, time.time()),
                        row["last_run"] or 0, row["last_status"] or "")
                except Exception:
                    await cb.answer(i18n.t("common.error", lang))
                    return
            await db.set_schedule_enabled(sid, now_on)
            await cb.answer(i18n.t("schedule.resumed" if now_on else "schedule.paused", lang))
        else:
            await cb.answer()
            return
        text, kb = await _render_schedules(uid, lang)
        if cb.message is not None:  # None for old or inaccessible message
            with contextlib.suppress(Exception):
                await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

    # ---- session browser ----
    # - /sessions: browse, search, and (DM) switch sessions
    # - paginated for Telegram limits
    # - per-message search keyword held in `browsers`
    _SESSIONS_PAGE = 6
    browsers: dict[tuple, str | None] = {}  # (chat_id, msg_id) to keyword

    async def _session_stats(thread_id: int) -> tuple[int, str]:
        try:
            tot = await db.get_usage_totals(thread_id)
        except Exception:
            tot = {}
        reqs = int(tot.get("requests", 0) or 0)
        toks = _fmt_tokens((tot.get("input", 0) or 0) + (tot.get("output", 0) or 0))
        return reqs, toks

    def _session_name(row: dict) -> str:
        return row["name"] or (
            "General" if row["thread_id"] == 0 else f"#{abs(row['thread_id'])}"
        )

    async def _render_sessions(
        chat_id: int, is_dm: bool, current_key: int, keyword: str | None,
        offset: int, lang: str = "en", idle_note: str | None = None,
        uname: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        # Collapse stray empty untitled sessions before listing.
        # - DM only, never the current one
        # - list then shows at most one live empty
        if is_dm:
            with contextlib.suppress(Exception):
                await _gc_untitled_empties(chat_id, current_key)
        rows, total = await db.browse_threads(
            chat_id, keyword or None, limit=_SESSIONS_PAGE, offset=offset
        )
        head = i18n.t("sessions.head_dm" if is_dm else "sessions.head_group", lang)
        if keyword:
            head += i18n.t("sessions.head_search", lang, kw=markup.escape_html(keyword))
        head += i18n.t("sessions.head_total", lang, total=total)
        lines = [head, ""]
        # Passive notice that opening /sessions auto-started a fresh session.
        # - never a push; shown only on open
        if idle_note:
            lines.append(idle_note)
            lines.append("")
        kb_rows: list[list[InlineKeyboardButton]] = []
        for r in rows:
            name = _session_name(r)
            mark = i18n.t("sessions.current_mark", lang) if r["thread_id"] == current_key else ""
            icon = mode_glyph(r["mode"])
            lines.append(i18n.t(
                # Icon conveys the mode; date is list noise.
                "sessions.row", lang, icon=icon,
                name=markup.escape_html(name), mark=mark,
            ))
            # Button is the session name; tap opens its options menu.
            label = f"{icon} {name[:40]}"
            if is_dm:
                # One full-width button per session, labeled with its name.
                # - tap opens the per-session options menu
                # - favorites sort first and are marked
                fav = bool(r.get("favorite"))
                kb_rows.append([
                    InlineKeyboardButton(
                        text=(f"⭐ {label}" if fav else label),
                        callback_data=f"ses:opts:{r['thread_id']}",
                    )
                ])
            elif r["thread_id"] > 0:
                internal = str(abs(chat_id))[3:]  # strip the -100 supergroup prefix
                kb_rows.append(
                    [InlineKeyboardButton(text=f"{label} ▸", url=f"https://t.me/c/{internal}/{r['thread_id']}")]
                )
        if not rows:
            lines.append(i18n.t("sessions.none_match", lang))
        # Paging buttons, shared by DM and group layouts.
        prev_btn = (InlineKeyboardButton(text=i18n.t("btn.prev", lang),
                                         callback_data=f"ses:pg:{max(0, offset - _SESSIONS_PAGE)}")
                    if offset > 0 else None)
        next_btn = (InlineKeyboardButton(text=i18n.t("btn.next", lang),
                                         callback_data=f"ses:pg:{offset + _SESSIONS_PAGE}")
                    if offset + _SESSIONS_PAGE < total else None)
        if is_dm:
            # New-chat row carries the pager.
            # - left arrow before it, right arrow after it
            # - page 1 shows only the right arrow
            # - no New code button; sessions are promoted with /code
            row = [b for b in (prev_btn,
                               InlineKeyboardButton(text=i18n.t("btn.new_chat", lang),
                                                    callback_data="ses:new:chat"),
                               next_btn) if b]
            kb_rows.append(row)
        else:
            nav = [b for b in (prev_btn, next_btn) if b]
            if nav:
                kb_rows.append(nav)
        kb_rows.append(
            [
                InlineKeyboardButton(text=i18n.t("btn.search", lang), callback_data="ses:find"),
                InlineKeyboardButton(text=i18n.t("btn.close", lang), callback_data="ses:close"),
            ]
        )
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)

    async def _open_sessions(message: Message, keyword: str | None = None,
                             idle_note: str | None = None) -> None:
        is_dm = message.chat.type == "private"
        chat_id = message.chat.id
        current = await _session_key(message)
        text, kb = await _render_sessions(
            chat_id, is_dm, current, keyword, 0, _lang(message), idle_note=idle_note,
            uname=(message.from_user.username if message.from_user else None),
        )
        send_kwargs: dict = {}
        if message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        sent = await _send_menu(chat_id, text, kb, **send_kwargs)
        if sent is not None:
            browsers[(chat_id, sent.message_id)] = keyword

    async def _session_switch_line(key: int, lang: str = "en") -> str:
        """Single confirmation line shown on switching into a session.

        - the other session details live in status and settings
        """
        st = await db.get_thread(key)
        if st is None:
            return i18n.t("common.switched", lang)
        name = st.name or ("General" if key == 0 else f"#{abs(key)}")
        line = i18n.t("session.switched_to", lang, glyph=mode_glyph(st.mode),
                      name=markup.escape_html(name)
                      + (" [shell]" if getattr(st, "shell_mode", False) else ""))
        # Also show what the session runs on (model, effort).
        with contextlib.suppress(Exception):
            line += "\n" + await _session_meta_line(st, lang)
        return line

    async def _session_card(key: int, lang: str = "en") -> str:
        st = await db.get_thread(key)
        if st is None:
            return i18n.t("common.switched", lang)
        name = st.name or ("General" if key == 0 else f"#{abs(key)}")
        lines = [
            i18n.t("session.switched_to", lang, glyph=mode_glyph(st.mode),
                   name=markup.escape_html(name)
                   + (" [shell]" if getattr(st, "shell_mode", False) else "")),
            # Meta line shows only model and effort from CLI.
            await _session_meta_line(st, lang),
        ]
        return "\n".join(lines)

    async def _owned_session(key: int, uid: int):
        """Return the `ThreadState` if `uid` owns DM session `key`.

        - ownership is `chat_id` or `created_by`; legacy rows carry one
        - gates every per-session options-menu action
        """
        st = await db.get_thread(key)
        if st is None or (st.chat_id != uid and st.created_by != uid):
            return None
        return st

    async def _session_options(key: int, lang: str):
        """Return `(text, keyboard)` for one session's options menu.

        - actions: switch, recap, rename, status, favorite, delete, back
        - returns `None` if the session is gone
        """
        st = await db.get_thread(key)
        if st is None:
            return None
        name = st.name or ("General" if key == 0 else f"#{abs(key)}")
        text = "\n".join([
            i18n.t("sessions.options_header", lang, glyph=mode_glyph(st.mode),
                   name=markup.escape_html(name)
                   + (" [shell]" if getattr(st, "shell_mode", False) else "")),
            # Meta line shows only model and effort from CLI.
            await _session_meta_line(st, lang),
        ])
        fav = bool(st.favorite)
        B = InlineKeyboardButton
        # Upgrade to code only if the session owner has access.
        # - downgrade code to chat; DM owner is the creator
        owner_uid = st.created_by or st.chat_id
        can_code = (owner_uid == settings.owner_id) or (allowlist.level_of(owner_uid, None) == "code")
        rows = [[B(text=i18n.t("btn.switch", lang), callback_data=f"ses:sw:{key}")]]
        # Recap runs the model; /last shows the verbatim exchange.
        rows += [
            [B(text=i18n.t("btn.recap", lang), callback_data=f"ses:recap:{key}"),
             B(text=i18n.t("btn.status", lang), callback_data=f"ses:status:{key}")],
            [B(text=i18n.t("btn.rename", lang), callback_data=f"ses:rename:{key}"),
             B(text=i18n.t("btn.unfavorite" if fav else "btn.favorite", lang),
               callback_data=f"ses:fav:{key}")],
        ]
        # Convert pairs with Export in code, Transcript in chat.
        # - no full-width high row
        convert_btn = None
        if st.mode == "chat" and can_code:
            convert_btn = B(text=i18n.t("btn.upgrade_code", lang), callback_data=f"ses:up:{key}")
        elif st.mode == "code":
            convert_btn = B(text=i18n.t("btn.downgrade_chat", lang), callback_data=f"ses:down:{key}")
        transcript_btn = B(text=i18n.t("btn.transcript", lang), callback_data=f"ses:hist:{key}")
        if st.mode == "code":
            # Transcript on its own; Convert paired with Export below.
            rows.append([transcript_btn])
            export_btn = B(text=i18n.t("btn.export_files", lang), callback_data=f"ses:exfiles:{key}")
            rows.append([convert_btn, export_btn] if convert_btn else [export_btn])
        else:
            # Chat: pair Transcript with Convert if owner has code access.
            content_row = [transcript_btn]
            if convert_btn is not None:
                content_row.append(convert_btn)
            rows.append(content_row)
        rows.append([
            B(text=i18n.t("btn.delete", lang), callback_data=f"ses:del:{key}"),
            B(text=i18n.t("btn.back", lang), callback_data="ses:pg:0"),
        ])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        return text, kb

    async def _repost_options(cb: CallbackQuery, key: int, lang: str) -> None:
        """Move the options menu to the bottom after posting content.

        - sends a fresh menu, then deletes the old one
        """
        opts = await _session_options(key, lang)
        if opts is None:
            return
        text, kb = opts
        with contextlib.suppress(Exception):
            await _send_menu(cb.message.chat.id, text, kb)
        with contextlib.suppress(Exception):
            await cb.message.delete()

    def _workdir_zip(key: int):
        """Zip the session's working directory into an in-memory archive.

        - returns `(BufferedInputFile, None)` or `(None, error_key)`
        - capped to fit Telegram's bot upload limit
        """
        # Workdir is named by public sid; zip only work files.
        # - state and transcript live in `<sid>/state`
        root = settings.base_workdir / db.session_pubid(key) / "work"  # ULID directory name
        files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        if not files:
            return None, "export.empty"
        total = 0
        for p in files:
            with contextlib.suppress(OSError):
                total += p.stat().st_size
        if total > 100 * 1024 * 1024:
            return None, "export.too_big"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                with contextlib.suppress(OSError):
                    zf.write(p, p.relative_to(root).as_posix())
        data = buf.getvalue()
        if len(data) > 49 * 1024 * 1024:
            return None, "export.too_big"
        # Name the archive by public sid, not the raw id.
        # - download doesn't leak internal numbering
        return BufferedInputFile(data, filename=f"session-{db.session_pubid(key)}-files.zip"), None

    @router.message(Command("sessions"))
    async def cmd_sessions(message: Message) -> None:
        """Browse, search, and switch sessions (DM) or topics (supergroup)."""
        await _ensure_state(message)
        # Opening /sessions after idle auto-starts a fresh current session.
        # - creation happens on interaction, not only chat turns
        _, rotated = await _rotate_if_idle(message)
        note = i18n.t("sessions.idle_rotated", _lang(message)) if rotated else None
        await _open_sessions(message, _command_arg(message) or None, idle_note=note)

    @router.callback_query(F.data.startswith("ses:"))
    async def on_sessions_cb(cb: CallbackQuery) -> None:
        try:
            parts = (cb.data or "").split(":")
            verb = parts[1] if len(parts) > 1 else ""
            msg = cb.message
            if msg is None:
                await cb.answer()
                return
            chat_id = msg.chat.id
            is_dm = msg.chat.type == "private"
            lang = _lang(cb)
            bkey = (chat_id, msg.message_id)
            keyword = browsers.get(bkey)
            if verb == "close":
                browsers.pop(bkey, None)
                with contextlib.suppress(Exception):
                    await msg.delete()
                await cb.answer()
                return
            if verb == "find":
                pending[(chat_id, thread_key(msg), cb.from_user.id)] = "sessearch"
                with contextlib.suppress(Exception):
                    await bot.send_message(
                        chat_id,
                        i18n.t("sessions.search_prompt", lang),
                        **({"message_thread_id": msg.message_thread_id} if msg.message_thread_id else {}),
                    )
                await cb.answer(i18n.t("sessions.search_toast", lang))
                return
            if verb == "opts" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                opts = await _session_options(key, lang)
                if opts is not None:
                    text, kb = opts
                    await _edit_menu(msg, text, kb)
                await cb.answer()
                return
            if verb in ("up", "down") and len(parts) > 2 and is_dm:
                # Upgrade or downgrade the session type, then re-render the menu.
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                new_mode = "code" if verb == "up" else "chat"
                _, ok = await _switch_session_mode(
                    key, cb.from_user.id, cb.from_user.username, new_mode, lang)
                if not ok:
                    await cb.answer(i18n.t("access.code_denied", lang), show_alert=True)
                    return
                opts = await _session_options(key, lang)
                if opts is not None:
                    text, kb = opts
                    await _edit_menu(msg, text, kb)
                await cb.answer(i18n.t("mode.switched_toast", lang, mode=i18n.mode_word(new_mode, lang)))
                return
            if verb == "recap" and len(parts) > 2 and is_dm:
                # Recap runs the model with the recap prompt and streams.
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                blk = await _access_block(cb.from_user.id, cb.from_user.username, lang, key)
                if blk:
                    await cb.answer(blk, show_alert=True)
                    return
                await cb.answer()  # ack before the model run streams
                with contextlib.suppress(Exception):
                    await sessions.handle_text(chat_id, key, i18n.t("recap.prompt", lang))
                return
            if verb == "status" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                with contextlib.suppress(Exception):
                    await bot.send_message(chat_id, await _session_card(key, lang), parse_mode="HTML")
                await _repost_options(cb, key, lang)
                await cb.answer()
                return
            if verb == "rename" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                pending[(chat_id, thread_key(msg), cb.from_user.id)] = f"rename:{key}"
                with contextlib.suppress(Exception):
                    await bot.send_message(chat_id, i18n.t("session.rename_prompt", lang))
                await cb.answer()
                return
            if verb == "hist" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                doc, note = await _history_doc(key, lang)
                if doc is None:
                    with contextlib.suppress(Exception):
                        await bot.send_message(chat_id, note, parse_mode="HTML")
                else:
                    with contextlib.suppress(Exception):
                        await bot.send_document(chat_id=chat_id, document=doc)
                await _repost_options(cb, key, lang)
                await cb.answer()
                return
            if verb == "exfiles" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                doc, err = _workdir_zip(key)
                if err:
                    with contextlib.suppress(Exception):
                        await bot.send_message(chat_id, i18n.t(err, lang), parse_mode="HTML")
                else:
                    with contextlib.suppress(Exception):
                        await bot.send_document(chat_id=chat_id, document=doc,
                                                caption=i18n.t("export.caption", lang))
                await _repost_options(cb, key, lang)
                await cb.answer()
                return
            if verb == "new" and len(parts) > 2 and is_dm:
                mode = parts[2] if parts[2] in VALID_MODES else "chat"
                uid = cb.from_user.id
                if mode == "code" and allowlist.level_of(uid, cb.from_user.username) != "code":
                    await cb.answer(i18n.t("access.code_denied", lang), show_alert=True)
                    return
                if await _session_limit_block(uid, cb.from_user.username, lang):
                    await cb.answer(i18n.t("session.limit_reached_short", lang), show_alert=True)
                    return
                await _new_dm_session(uid, mode, _default_session_name(mode, lang))
                # New-chat tap dismisses the sessions browser entirely.
                # - new empty session is current; user just types
                # - collapse stray empties first
                with contextlib.suppress(Exception):
                    await _gc_untitled_empties(uid, await db.get_dm_current(uid) or 0)
                browsers.pop(bkey, None)
                with contextlib.suppress(Exception):
                    await msg.delete()
                await cb.answer(i18n.t("sessions.new_chat_toast", lang))
                return
            if verb == "sw" and len(parts) > 2:
                key = int(parts[2])
                if is_dm:
                    # Only the tapper's own DM session may be switched to.
                    # - a forged callback_data must not target another user's session
                    st = await db.get_thread(key)
                    if key >= 0 or st is None or st.chat_id != cb.from_user.id:
                        await cb.answer()
                        return
                    # A chat-level user may not switch into a code session.
                    if st.mode == "code" and allowlist.level_of(cb.from_user.id, cb.from_user.username) != "code":
                        await cb.answer(i18n.t("access.code_denied", lang), show_alert=True)
                        return
                    await db.set_dm_current(cb.from_user.id, key)
                    # An explicit switch counts as user activity.
                    # - stamp last-active so the next message continues it
                    # - never idle-rotate a deliberately chosen session
                    with contextlib.suppress(Exception):
                        await db.set_user_last_active(cb.from_user.id, time.time())
                    # Switching into a real session collapses empty untitled leftovers.
                    with contextlib.suppress(Exception):
                        await _gc_untitled_empties(cb.from_user.id, key)
                    # Switching shows only a one-line confirmation.
                    # - Recap/Transcript live in the options menu
                    with contextlib.suppress(Exception):
                        await _send_menu(chat_id, await _session_switch_line(key, lang))
                    # Close the stale options menu the Switch button came from.
                    with contextlib.suppress(Exception):
                        await msg.delete()
                await cb.answer(i18n.t("common.switched", lang))
                return
            if verb == "fav" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                st = await _owned_session(key, cb.from_user.id)
                if st is None:
                    await cb.answer()
                    return
                new_fav = not bool(st.favorite)
                with contextlib.suppress(Exception):
                    await db.set_favorite(key, new_fav)
                # Re-render the options menu so the star toggles in place.
                opts = await _session_options(key, lang)
                if opts is not None:
                    text, kb = opts
                    await _edit_menu(msg, text, kb)
                await cb.answer(
                    i18n.t("common.favorited" if new_fav else "common.unfavorited", lang)
                )
                return
            if verb == "del" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                st = await db.get_thread(key)
                name = (st.name if st else None) or f"#{abs(key)}"
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=i18n.t("btn.delete", lang), callback_data=f"ses:delok:{key}"),
                    InlineKeyboardButton(text=i18n.t("btn.cancel", lang), callback_data="ses:pg:0"),
                ]])
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("session.delete_confirm", lang, name=markup.escape_html(name)),
                        kb,
                    )
                await cb.answer()
                return
            if verb == "delok" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                uid = cb.from_user.id
                # Capture the name before the row is dropped.
                st = await db.get_thread(key)
                sname = (st.name if st else None)
                # Tear down any live worker, then drop row and workdir.
                with contextlib.suppress(Exception):
                    await sessions.reset(key)
                deleted = False
                with contextlib.suppress(Exception):
                    deleted = await db.delete_dm_session(uid, key)
                if deleted:
                    with contextlib.suppress(Exception):
                        # Workdirs are named by public ULID, not raw key.
                        sid = db.session_pubid(key)
                        # Archive to cold storage instead of deleting.
                        # - the transcript lives outside the workdir, in `~/.claude/projects/`
                        archive.archive_session(
                            settings.base_workdir, sid,
                            owner_id=uid, key=key, name=sname,
                        )
                    # If the deleted session was current, switch to the latest.
                    # - else create a fresh default so one always exists
                    if await db.get_dm_current(uid) == key:
                        remaining, _ = await db.browse_threads(uid, None, limit=1, offset=0)
                        if remaining:
                            await db.set_dm_current(uid, remaining[0]["thread_id"])
                        else:
                            nk = await db.allocate_dm_session(
                                uid, i18n.t("session.first_default", lang),
                                settings.default_model, str(settings.base_workdir),
                            )
                            await db.set_dm_current(uid, nk)
                current = await db.get_dm_current(uid)
                text, kb = await _render_sessions(chat_id, is_dm, current or 0, keyword, 0, lang,
                                                  uname=cb.from_user.username)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer(
                    i18n.t("common.deleted" if deleted else "session.delete_failed", lang)
                )
                return
            if verb == "pg" and len(parts) > 2:
                offset = int(parts[2])
                current = (
                    await db.get_dm_current(cb.from_user.id) if is_dm else thread_key(msg)
                )
                text, kb = await _render_sessions(chat_id, is_dm, current or 0, keyword, offset, lang,
                                                  uname=cb.from_user.username)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer()
                return
            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ---- commands ----

    # Help groups in display order (group key to header key).
    _HELP_GROUPS = (
        ("sessions", "help.group_sessions"),
        ("settings", "help.group_settings"),
        ("run", "help.group_run"),
        ("code", "help.group_code"),
        ("meta", "help.group_meta"),
        ("owner", "help.group_owner"),
    )

    def _help_text(message: Message) -> str:
        """Generate help from the command registry.

        - intro, then one section per help group, then the footer
        - filtered to the user's access
        - stays in sync with `commands.COMMANDS`
        """
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        is_owner = uid == settings.owner_id
        is_code = is_owner or (allowlist.level_of(uid, uname) == "code")
        parts = [i18n.t("help.intro", lang)]
        for gkey, hdr in _HELP_GROUPS:
            lines = []
            for c in commands.COMMANDS:
                if c.help_group != gkey:
                    continue
                if c.scope == "owner" and not is_owner:
                    continue
                if c.scope == "code" and not is_code:
                    continue
                label = c.label.get(lang) or c.label.get("en") or c.slug
                lines.append(f"/{c.slug} — {markup.escape_html(label)}")
            if lines:
                parts.append(i18n.t(hdr, lang) + "\n" + "\n".join(lines))
        parts.append(i18n.t("help.footer", lang))
        return "\n\n".join(parts)

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await _ensure_state(message)
        await reply(message, _help_text(message))

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await _ensure_state(message)
        await reply(message, _help_text(message))

    @router.message(Command("newchat"))
    async def cmd_newchat(message: Message) -> None:
        """Create a chat session, promotable to code. Optional name."""
        await _ensure_state(message)
        await _do_new(message, f"chat {_command_arg(message)}".strip())

    @router.message(Command("newcode"))
    async def cmd_newcode(message: Message) -> None:
        """Create a code session, downgradable to chat. Optional name."""
        await _ensure_state(message)
        await _do_new(message, f"code {_command_arg(message)}".strip())

    @router.message(Command("new"))
    async def cmd_new(message: Message) -> None:
        """Create a new session, born as chat. Optional name.

        - upgrade to code later for files or a terminal
        """
        await _ensure_state(message)
        await _do_new(message, _command_arg(message))

    async def _switch_session_mode(key: int, uid: int, uname, new_mode: str, lang: str):
        """Switch a session to `new_mode`, carrying its conversation.

        - an upgrade to code is gated by access level
        - workdir files persist either way
        - returns `(reply_text, ok)`
        """
        st = await db.get_thread(key)
        if st is None:
            return i18n.t("common.error", lang), False
        if st.mode == new_mode:
            return i18n.t("mode.already", lang, mode=i18n.mode_word(new_mode, lang)), False
        if new_mode == "code" and not (uid == settings.owner_id
                                       or allowlist.level_of(uid, uname) == "code"):
            return i18n.t("access.code_denied", lang), False
        await db.switch_mode(key, new_mode)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        msg_key = "mode.upgraded" if new_mode == "code" else "mode.downgraded"
        return i18n.t(msg_key, lang, glyph=mode_glyph(new_mode),
                      tagline=mode_tagline(new_mode, lang=lang), defer=defer), True

    @router.message(Command("code"))
    async def cmd_code(message: Message) -> None:
        """Upgrade the current session to code; needs code access.

        - keeps the conversation, adds a workdir and full toolset
        """
        await _ensure_state(message)
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        text, _ = await _switch_session_mode(key, uid, uname, "code", _lang(message))
        await reply(message, text)

    @router.message(Command("chat"))
    async def cmd_chat(message: Message) -> None:
        """Downgrade the current session to chat.

        - keeps the conversation and the workdir files
        - code tools are unavailable until upgraded again
        """
        await _ensure_state(message)
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        text, _ = await _switch_session_mode(key, uid, uname, "chat", _lang(message))
        await reply(message, text)

    @router.message(Command("mode"))
    async def cmd_mode(message: Message) -> None:
        """Toggle this session's type between chat and code.

        - carries the conversation and workdir files
        - upgrading needs code access; a guest is denied
        """
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        new_mode = "code" if state.mode == "chat" else "chat"
        text, _ok = await _switch_session_mode(key, uid, uname, new_mode, lang)
        await reply(message, text)

    @router.message(Command("model"))
    async def cmd_model(message: Message) -> None:
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        arg = _command_arg(message)

        if not arg:
            # No arg: show the unified hub picker.
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "model"):
                return
            await reply(message, i18n.t("model.pick", lang,
                                        model=markup.escape_html(models.label(state.model))))
            return

        # Resolve a friendly alias or exact model id; reject others.
        # - accepted set is the CLI's own catalog
        # - unknown arg falls back to the picker
        model = models.match(arg)
        if model is None:
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "model"):
                return
            await reply(message, i18n.t("model.pick", lang,
                                        model=markup.escape_html(models.label(state.model))))
            return

        await db.set_model(key, model)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(
            message,
            # Show what the alias resolves to.
            i18n.t("model.set", lang, model=markup.escape_html(models.label(model)), defer=defer),
        )

    # ---- Pro commands: /effort /maxturns /dirs /fork ----

    @router.message(Command("effort"))
    async def cmd_effort(message: Message) -> None:
        """Show or set reasoning effort."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        may_max = _may_max_effort(uid, uname)
        arg = _command_arg(message).lower().strip()
        if not arg:
            # No arg: show the unified hub picker.
            # - gated `max` level hidden for users not allowed it
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "effort"):
                return
            cur = (_effort_label(state.effort, lang) if state.effort
                   else _effort_default_label(state.model, lang))
            await reply(message, i18n.t("effort.pick", lang, cur=markup.escape_html(cur)))
            return
        if arg in ("default", "reset", "none"):
            await db.set_effort(key, None)
            deferred = await _rebuild_session(key)
            defer = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("effort.reset", lang, defer=defer))
            return
        # Accepted levels come from the CLI for this model.
        levels = models.effort_levels(state.model or settings.default_model)
        if not levels and models.entries():
            await reply(message, i18n.t("effort.unsupported", lang,
                                        model=markup.escape_html(models.label(state.model))))
            return
        if arg not in levels:
            shown = [lv for lv in levels if lv != "max" or may_max]
            await reply(message, i18n.t("effort.usage", lang,
                                        levels=markup.escape_html("|".join(shown) or "…")))
            return
        if arg == "max" and not may_max:
            await reply(message, i18n.t("effort.max_denied", lang))
            return
        await db.set_effort(key, arg)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        # Show the level under its translated name.
        await reply(message, i18n.t("effort.set", lang,
                                    val=markup.escape_html(_effort_label(arg, lang)), defer=defer))

    @router.message(Command("maxturns"))
    async def cmd_maxturns(message: Message) -> None:
        """Show or set the agentic turn cap: N or off."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        arg = _command_arg(message).lower().strip()
        if not arg:
            # No arg: show the hub picker; code-only.
            # - in a chat session, show the value instead
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if state.mode == "code" and await _send_setting_picker(
                    message.chat.id, key, uid, uname, lang, "max_turns"):
                return
            cur = str(state.max_turns) if state.max_turns else i18n.t("maxturns.unlimited", lang)
            await reply(message, i18n.t("maxturns.show", lang, cur=cur))
            return
        if arg in ("off", "none", "0", "unlimited"):
            await db.set_max_turns(key, None)
            deferred = await _rebuild_session(key)
            defer = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("maxturns.set_unlimited", lang, defer=defer))
            return
        try:
            n = int(arg)
            if not (1 <= n <= 1000):
                raise ValueError
        except ValueError:
            await reply(message, i18n.t("maxturns.usage", lang))
            return
        await db.set_max_turns(key, n)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("maxturns.set", lang, n=n, defer=defer))

    @router.message(Command("fork"))
    async def cmd_fork(message: Message) -> None:
        """Branch the current session into a new one sharing history.

        - the original is left untouched; DM only
        """
        state = await _ensure_state(message)
        lang = _lang(message)
        if message.chat.type != "private":
            await reply(message, i18n.t("fork.dm_only", lang))
            return
        if state is None:
            await reply(message, i18n.t("fork.no_session", lang))
            return
        cur_sid = state.code_session_id if state.mode == "code" else state.chat_session_id
        if not cur_sid:
            await reply(message, i18n.t("fork.empty", lang))
            return
        uid = message.chat.id
        base_name = state.name or _default_session_name(state.mode, lang)
        name = i18n.t("session.fork_name", lang, base=base_name)
        block = await _session_limit_block(
            uid, message.from_user.username if message.from_user else None, lang)
        if block:
            await reply(message, block)
            return
        new_key = await _new_dm_session(uid, state.mode, name)
        # Seed the branch from the current underlying session id.
        # - fork on first turn so the original isn't mutated
        if state.mode == "code":
            await db.set_code_session(new_key, cur_sid)
        else:
            await db.set_chat_session(new_key, cur_sid)
        await db.set_fork_pending(new_key, True)
        await db.set_model(new_key, state.model)
        await reply(
            message,
            i18n.t("fork.done", lang, glyph=mode_glyph(state.mode),
                   name=markup.escape_html(name)),
        )

    @router.message(Command("clear", "reset"))
    async def cmd_reset(message: Message) -> None:
        """Clear the session context and start fresh.

        - cancels the run and drops resume ids and transcript
        - `/reset` remains an alias
        """
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        try:
            await sessions.reset(key)
        except Exception as exc:
            await reply(
                message,
                i18n.t("session.clear_error", lang, err=markup.escape_html(str(exc))),
            )
            return
        await reply(message, i18n.t("session.cleared", lang))

    # `/memory` (1M-context toggle) is retired.
    # - 1M is the native window of current models
    # - `big_memory` column and `db.set_big_memory` stay intact

    @router.message(Command("forget"))
    async def cmd_forget(message: Message) -> None:
        """Clear this topic's agent-saved session memory."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        # Session memory is code-only; reject in chat sessions.
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        # Gate on the caller's level too, not just session mode.
        # - demoted user must not wipe memory via stale session
        if not _has_code_access(message.from_user.id if message.from_user else 0,
                                message.from_user.username if message.from_user else None):
            await reply(message, i18n.t("access.code_denied", lang))
            return
        prior = (state.session_notes or "").strip()
        if not prior:
            await reply(message, i18n.t("forget.empty", lang))
            return
        await db.set_session_notes(key, "")
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("forget.done", lang, n=len(prior), note=note))

    def _build_tree(root: Path, max_entries: int = 120, max_depth: int = 4) -> str:
        """Compact read-only directory tree, capped in depth and entries."""
        out: list[str] = []
        state = {"count": 0, "truncated": False}

        def walk(d: Path, prefix: str, depth: int) -> None:
            if depth > max_depth or state["truncated"]:
                return
            try:
                entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except Exception:
                return
            for i, p in enumerate(entries):
                if state["count"] >= max_entries:
                    state["truncated"] = True
                    return
                last = i == len(entries) - 1
                out.append(f"{prefix}{'└─ ' if last else '├─ '}{p.name}{'/' if p.is_dir() else ''}")
                state["count"] += 1
                if p.is_dir():
                    walk(p, prefix + ("   " if last else "│  "), depth + 1)

        walk(root, "", 1)
        body = "\n".join(out) if out else "(empty)"
        if state["truncated"]:
            body += "\n… (truncated)"
        return body

    @router.message(Command("files"))
    async def cmd_files(message: Message) -> None:
        """Read-only tree of the current session's working directory.

        - a session's working dir is fixed
        """
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        root = Path(state.cwd)
        # Show the session name, never the host path.
        # - path leaked internal numbering and parent directory
        # - user sees only files they create
        ws_name = markup.escape_html(state.name or _default_session_name(state.mode, lang))
        if not root.exists():
            await reply(message, i18n.t("files.empty", lang, name=ws_name))
            return
        tree = _build_tree(root)
        body = (
            f"{i18n.t('files.header', lang, name=ws_name)}\n"
            f"<pre>{markup.escape_html(tree)}</pre>"
        )
        if len(body) <= markup.SAFE_LIMIT:
            await reply(message, body)
        else:
            # Big trees won't fit a message; send a text document.
            # - header uses the session name, not the host path
            with contextlib.suppress(Exception):
                doc = markup.as_document(f"{state.name or ''}\n\n{tree}".strip(), "files.txt")
                await bot.send_document(chat_id=message.chat.id, document=doc)

    @router.message(Command("export"))
    async def cmd_export(message: Message) -> None:
        """Export the code session's working-directory files as a .zip."""
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        key = await _session_key(message)
        doc, err = _workdir_zip(key)
        if err:
            await reply(message, i18n.t(err, lang))
            return
        with contextlib.suppress(Exception):
            await bot.send_document(
                chat_id=message.chat.id, document=doc, caption=i18n.t("export.caption", lang)
            )

    # ---- /secret ----
    # - per-session service credentials, e.g. a GitHub token
    # - stored in `<sid>/secrets.env`, root-owned 0600, outside the workdir
    # - injected as env vars into this session's jail only
    # - owner credentials never enter any jail; values never echoed
    _SECRET_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _secrets_path(key: int) -> Path:
        return settings.base_workdir / db.session_pubid(key) / "secrets.env"  # ULID directory name

    def _read_secrets(key: int) -> dict[str, str]:
        out: dict[str, str] = {}
        path = _secrets_path(key)
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if _SECRET_KEY_RE.match(k):
                        out[k] = v
        return out

    def _write_secrets(key: int, secrets: dict[str, str]) -> None:
        path = _secrets_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text("".join(f"{k}={v}\n" for k, v in secrets.items()), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)   # atomic swap; mode 0600, root-readable

    async def _do_secret(message: Message, text: str) -> None:
        lang = _lang(message)
        key = await _session_key(message)
        text = (text or "").strip()
        secrets = _read_secrets(key)
        low = text.lower()
        if low == "clear" or low.startswith("clear "):
            target = text[6:].strip() if low.startswith("clear ") else ""
            if target:
                secrets.pop(target, None)
                _write_secrets(key, secrets)
                await reply(message, i18n.t("secret.cleared", lang, what=markup.escape_html(target)))
            else:
                _write_secrets(key, {})
                await reply(message, i18n.t("secret.cleared", lang, what=i18n.t("secret.all", lang)))
            return
        if "=" in text:
            k, v = text.split("=", 1)
            k = k.strip()
            if not _SECRET_KEY_RE.match(k):
                await reply(message, i18n.t("secret.bad_name", lang))
                return
            secrets[k] = v.strip()
            _write_secrets(key, secrets)
            await reply(message, i18n.t("secret.stored", lang, name=markup.escape_html(k)))
            return
        # No parseable arg: list current names (never values) and prompt.
        # - captures next message as the `KEY=VALUE` to add
        names = (", ".join(f"<code>{markup.escape_html(n)}</code>" for n in secrets)
                 or i18n.t("secret.none", lang))
        pending[_pkey(message)] = "secret"
        # Attach a How-to-use button linking the guide.
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=i18n.t("secret.btn_guide", lang), callback_data="secret:guide")]])
        skw: dict = {}
        if getattr(message, "message_thread_id", None) is not None:
            skw["message_thread_id"] = message.message_thread_id
        await _send_menu(message.chat.id, i18n.t("secret.help", lang, names=names), kb, **skw)

    @router.message(Command("secret"))
    async def cmd_secret(message: Message) -> None:
        """Store a per-session service credential as an env var.

        - injected into this session's jail only
        - code sessions only
        """
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        # Gate on the user's level too, not just session mode.
        # - a demoted user may still own a code session
        if not _has_code_access(message.from_user.id if message.from_user else 0,
                                message.from_user.username if message.from_user else None):
            await reply(message, i18n.t("access.code_denied", lang))
            return
        await _do_secret(message, _command_arg(message))

    @router.callback_query(F.data == "secret:guide")
    async def on_secret_guide_cb(cb: CallbackQuery) -> None:
        """Show the detailed how-to behind the "How to use" button.

        - includes the GitHub-over-HTTPS walkthrough
        """
        lang = _lang(cb)
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _send_menu(cb.message.chat.id, i18n.t("secret.guide", lang))
        with contextlib.suppress(Exception):
            await cb.answer()

    @router.message(Command("sandbox"))
    async def cmd_sandbox(message: Message) -> None:
        """Answer a typed sandbox command; changes nothing.

        - the sandbox is mandatory for every session, with no opt-out
        - the toggle is retired
        """
        await _ensure_state(message)
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        await reply(message, i18n.t("sandbox.mandatory", lang))

    @router.message(Command("permissions"))
    async def cmd_permissions(message: Message) -> None:
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        # Permissions apply only to code sessions.
        # - chat has only auto-approved read-only web tools
        # - engine hardcodes default mode for chat; setting inert
        if state.mode != "code":
            await reply(message, i18n.t("perm.chat_na", lang))
            return
        # Gate on the caller's level too (demotion gap).
        if not _has_code_access(message.from_user.id if message.from_user else 0,
                                message.from_user.username if message.from_user else None):
            await reply(message, i18n.t("access.code_denied", lang))
            return
        arg = _command_arg(message).lower()

        if not arg:
            # No arg: show the hub picker; text list is fallback.
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "permission_mode"):
                return
            # Unset defaults to `acceptEdits`.
            current = PERM_MODE_TO_NAME.get(state.permission_mode or "acceptEdits", "auto-edits")
            lines = [
                i18n.t("perm.current", lang, current=current),
                "",
                i18n.t("perm.policies_header", lang),
            ]
            for name in PERM_NAME_TO_MODE:
                lines.append(i18n.t("perm.line", lang, name=name,
                                    help=i18n.t(f"perm.help.{name}", lang)))
            await reply(message, "\n".join(lines))
            return

        if arg not in PERM_NAME_TO_MODE:
            names = ", ".join(f"<code>{n}</code>" for n in PERM_NAME_TO_MODE)
            await reply(message, i18n.t("perm.unknown", lang, names=names))
            return

        # Full-access is available to all code users; sandbox confines it.

        sdk_mode = PERM_NAME_TO_MODE[arg]
        await db.set_permission_mode(key, sdk_mode)
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""

        if arg == "full-access":
            await reply(message, i18n.t("perm.set_full_access", lang, note=note))
        else:
            await reply(
                message,
                i18n.t("perm.set", lang, name=arg,
                       help=i18n.t(f"perm.help.{arg}", lang), note=note),
            )

    @router.message(Command("auto"))
    async def cmd_auto(message: Message) -> None:
        """Owner shortcut toggling code-mode auto-approval.

        - on: `bypassPermissions`, runs every tool without asking
        - off: `default`, asks for dangerous tools
        """
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("auto.owner_only", lang))
            return
        state = await _ensure_state(message)
        key = await _session_key(message)
        arg = _command_arg(message).lower()
        is_on = state.permission_mode == "bypassPermissions"

        if not arg:
            # No arg: toggle in place rather than show-only reply.
            new_on = not is_on
            # Off sets the auto-edits floor.
            await db.set_permission_mode(key, "bypassPermissions" if new_on else "acceptEdits")
            deferred = await _rebuild_session(key)
            note = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("auto.on" if new_on else "auto.off", lang, note=note))
            return
        if arg not in ("on", "off"):
            await reply(message, i18n.t("auto.usage", lang))
            return

        new_mode = "bypassPermissions" if arg == "on" else "acceptEdits"
        await db.set_permission_mode(key, new_mode)
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("auto.on" if arg == "on" else "auto.off", lang, note=note))

    @router.message(Command("shell"))
    async def cmd_shell(message: Message) -> None:
        """Toggle shell mode for this code session.

        - every message runs as a jail command, no model
        - does not change the session type
        """
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("shell.code_only", lang))
            return
        # Gate on the caller's level too (demotion gap).
        if not _has_code_access(message.from_user.id if message.from_user else 0,
                                message.from_user.username if message.from_user else None):
            await reply(message, i18n.t("access.code_denied", lang))
            return
        key = await _session_key(message)
        new_on = not bool(state.shell_mode)
        # Capture live keypad message and paused render before toggling.
        kb_ref = sessions.shell_kb_ref(key)
        resume_render = sessions.shell_resume_render(key)
        await sessions.set_shell_mode(key, new_on)
        if not new_on and kb_ref is not None:
            # Detach strips the stale keypad; back in agent mode.
            cid, mid = kb_ref
            with contextlib.suppress(Exception):
                await bot(EditRichMessage(
                    chat_id=cid, message_id=mid,
                    rich_message={"markdown": resume_render or "```\n(shell)\n```"},
                    reply_markup=None))
            sessions.set_shell_kb(key, None, None)
        await reply(message, i18n.t("shell.on" if new_on else "shell.off", lang))
        if new_on and resume_render is not None:
            # Re-attach with a waiting command re-offers the keypad.
            # - user continues instead of restarting the flow
            # - refresh first in case the program advanced
            live = await sessions.shell_refresh(key, lang)
            render = live or resume_render
            send_kwargs = ({"message_thread_id": message.message_thread_id}
                           if message.message_thread_id else {})
            with contextlib.suppress(Exception):
                sent = await bot(SendRichMessage(
                    chat_id=message.chat.id,
                    rich_message={"markdown": render},
                    reply_markup=_sessions.shell_keypad(), **send_kwargs))
                sessions.set_shell_kb(key, message.chat.id,
                                      getattr(sent, "message_id", None), render)

    @router.message(Command("usage"))
    async def cmd_usage(message: Message) -> None:
        await _ensure_state(message)
        lang = _lang(message)
        arg = _command_arg(message).lower()

        if not arg:
            cur = getattr(sessions, "usage_mode", "footer")
            # Owner gets the hub usage picker; others a read-only text.
            # - display is account-wide
            if _is_owner(message):
                with contextlib.suppress(Exception):
                    await _send_menu(
                        message.chat.id,
                        i18n.t("settings.v2_pick", lang, name=i18n.t("settings.usage_name", lang)),
                        _ss_usage_keyboard(cur, lang))
                return
            lines = [
                i18n.t("usage.current", lang, current=markup.escape_html(str(cur))),
                "",
                i18n.t("usage.modes_header", lang),
            ]
            for name in VALID_USAGE_MODES:
                lines.append(i18n.t("usage.line", lang, name=name,
                                    help=i18n.t(f"usage.help.{name}", lang)))
            await reply(message, "\n".join(lines))
            return

        if arg not in VALID_USAGE_MODES:
            names = ", ".join(f"<code>{n}</code>" for n in VALID_USAGE_MODES)
            await reply(message, i18n.t("usage.unknown", lang, names=names))
            return

        # Usage display is global; only the owner may change it.
        # - a guest could flip the display for everyone
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_usage", lang))
            return

        # Prefer the SessionManager setter; fall back to the attribute.
        # - keeps the command working if the helper is unavailable
        setter = getattr(sessions, "set_usage_mode", None)
        if callable(setter):
            await setter(arg)
        else:
            sessions.usage_mode = arg
        await reply(
            message,
            i18n.t("usage.set", lang, name=arg, help=i18n.t(f"usage.help.{arg}", lang)),
        )

    # ---- /codesplit (owner): each code block as own message ----
    # - workaround while mobile Telegram lacks a per-block copy button
    # - separate messages let long-press Copy grab the whole snippet
    # - owner-toggleable so it's easy to turn off later
    def _codesplit_kb(cur: bool, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        return InlineKeyboardMarkup(inline_keyboard=[[
            B(text=("✓ " if cur else "") + i18n.onoff(True, lang), callback_data="csm:on"),
            B(text=("✓ " if not cur else "") + i18n.onoff(False, lang), callback_data="csm:off"),
        ]])

    @router.message(Command("codesplit"))
    async def cmd_codesplit(message: Message) -> None:
        """Owner: toggle sending each fenced code block separately.

        - global and persisted; affects the next reply
        """
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("codesplit.owner_only", lang))
            return
        cur = bool(getattr(sessions, "split_code_messages", True))
        arg = _command_arg(message).strip().lower()
        if arg in ("on", "off"):
            await sessions.set_split_code_messages(arg == "on")
            await reply(message, i18n.t("codesplit.set", lang, state=i18n.onoff(arg == "on", lang)))
            return
        with contextlib.suppress(Exception):
            await _send_menu(
                message.chat.id,
                i18n.t("codesplit.show", lang, state=i18n.onoff(cur, lang)),
                _codesplit_kb(cur, lang),
            )

    @router.callback_query(F.data.startswith("csm:"))
    async def on_codesplit_cb(cb: CallbackQuery) -> None:
        """Apply a code-split toggle tap (owner-only, global setting)."""
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("codesplit.owner_only", lang))
            return
        val = (cb.data or "csm:on").split(":", 1)[1] == "on"
        await sessions.set_split_code_messages(val)
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(
                    cb.message,
                    i18n.t("codesplit.show", lang, state=i18n.onoff(val, lang)),
                    _codesplit_kb(val, lang),
                )
        with contextlib.suppress(Exception):
            await cb.answer(i18n.t("settings.saved", lang))

    def _workingplate_kb(cur: bool, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        return InlineKeyboardMarkup(inline_keyboard=[[
            B(text=("✓ " if cur else "") + i18n.onoff(True, lang), callback_data="wpl:on"),
            B(text=("✓ " if not cur else "") + i18n.onoff(False, lang), callback_data="wpl:off"),
        ]])

    @router.message(Command("workingplate"))
    async def cmd_workingplate(message: Message) -> None:
        """Owner: globally toggle the "Working…" plus Stop control plate.

        - off means no plate at all
        - global and persisted; affects the next turn
        """
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("codesplit.owner_only", lang))
            return
        cur = bool(getattr(sessions, "working_plate", True))
        arg = _command_arg(message).strip().lower()
        if arg in ("on", "off"):
            await sessions.set_working_plate(arg == "on")
            await reply(message, i18n.t("workingplate.set", lang, state=i18n.onoff(arg == "on", lang)))
            return
        with contextlib.suppress(Exception):
            await _send_menu(
                message.chat.id,
                i18n.t("workingplate.show", lang, state=i18n.onoff(cur, lang)),
                _workingplate_kb(cur, lang),
            )

    @router.callback_query(F.data.startswith("wpl:"))
    async def on_workplate_cb(cb: CallbackQuery) -> None:
        """Apply a working-plate toggle tap (owner-only, global setting)."""
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("codesplit.owner_only", lang))
            return
        val = (cb.data or "wpl:on").split(":", 1)[1] == "on"
        await sessions.set_working_plate(val)
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(
                    cb.message,
                    i18n.t("workingplate.show", lang, state=i18n.onoff(val, lang)),
                    _workingplate_kb(val, lang),
                )
        with contextlib.suppress(Exception):
            await cb.answer(i18n.t("settings.saved", lang))

    @router.message(Command("whoami"))
    async def cmd_whoami(message: Message) -> None:
        lang = _lang(message)
        user = message.from_user
        uid = getattr(user, "id", None)
        uname = getattr(user, "username", None)
        lines = [i18n.t("whoami", lang, uid=uid, uname=uname or "-")]
        # Per-user rolling usage and caps, shown to the user.
        if uid is not None:
            try:
                bd = await db.get_user_breakdown(uid)
                lines.append(i18n.t("whoami.usage", lang, day=_fmt_tokens(bd["day"]),
                                    week=_fmt_tokens(bd["week"]), total=_fmt_tokens(bd["total"])))
                rate = allowlist.rate_of(uid, uname)
                if rate.get("day") is not None or rate.get("week") is not None:
                    lines.append(i18n.t("whoami.caps", lang, caps=_fmt_caps(rate, lang)))
            except Exception:
                pass
        await reply(message, "\n".join(lines))

    def _parse_grant(arg: str) -> tuple[str, str | None, str | None, str | None]:
        """Parse `<id|@user> [chat|code] [until DATE]` arguments.

        - returns `(target, level|None, expiry|None, error_key|None)`
        """
        toks = arg.split()
        target = toks[0]
        level: str | None = None
        expiry: str | None = None
        i = 1
        while i < len(toks):
            t = toks[i].lower()
            if t in VALID_MODES:
                level = t
                i += 1
            elif t in ("until", "till") and i + 1 < len(toks):
                expiry = normalize_date(toks[i + 1])
                if expiry is None:
                    return target, level, None, "allow.bad_date"
                i += 2
            else:
                return target, level, expiry, "allow.bad_arg"
        return target, level, expiry, None

    async def _do_allow(message: Message, arg: str) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        target, level, expiry, err = _parse_grant(arg)
        if err:
            await reply(message, i18n.t(err, lang))
            return
        kind, val = allowlist.add(target, level=level, expires_at=expiry)
        if kind == "invalid":
            await reply(message, i18n.t("allow.invalid", lang, val=markup.escape_html(val)))
            return
        if kind == "owner":
            await reply(message, i18n.t("allow.owner", lang))
            return
        until = i18n.t("allow.until", lang, date=markup.escape_html(expiry)) if expiry else ""
        await reply(
            message,
            i18n.t("allow.granted", lang, val=markup.escape_html(val),
                   level=(level or "chat"), until=until),
        )

    @router.message(Command("allow"))
    async def cmd_allow(message: Message) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            # No arg: prompt and capture the next message.
            pending[_pkey(message)] = "allow"
            await reply(message, i18n.t("allow.prompt", lang))
            return
        await _do_allow(message, arg)

    async def _do_deny(message: Message, arg: str) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        if allowlist.remove(arg):
            await reply(message, i18n.t("deny.revoked", lang, val=markup.escape_html(arg)))
        else:
            await reply(message, i18n.t("deny.not_found", lang, val=markup.escape_html(arg)))

    @router.message(Command("deny"))
    async def cmd_deny(message: Message) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            # No arg: prompt and capture the next message.
            pending[_pkey(message)] = "deny"
            await reply(message, i18n.t("deny.prompt", lang))
            return
        await _do_deny(message, arg)

    async def _do_level(message: Message, arg: str) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        toks = arg.split()
        if not toks:
            await reply(message, i18n.t("level.usage", lang))
            return
        target = toks[0]
        # Full form "<user> chat|code" applies directly.
        if len(toks) >= 2 and toks[1].lower() in VALID_MODES:
            lvl = toks[1].lower()
            if allowlist.set_level(target, lvl):
                await reply(message, i18n.t("level.set", lang, val=markup.escape_html(target), level=lvl))
            else:
                await reply(message, i18n.t("level.not_found", lang, val=markup.escape_html(target)))
            return
        # No valid level: show a chat|code picker.
        # - callback_data is capped at 64 bytes
        # - a `:` in the target breaks the parse
        # - such targets are treated as not-found
        if ":" in target or len(f"setlvl:{target}:code".encode()) > 64:
            await reply(message, i18n.t("level.not_found", lang, val=markup.escape_html(target)))
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.t("level.pick_chat", lang),
                                 callback_data=f"setlvl:{target}:chat"),
            InlineKeyboardButton(text=i18n.t("level.pick_code", lang),
                                 callback_data=f"setlvl:{target}:code"),
        ]])
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        await _send_menu(message.chat.id,
                         i18n.t("level.pick", lang, val=markup.escape_html(target)),
                         kb, **send_kwargs)

    @router.message(Command("level"))
    async def cmd_level(message: Message) -> None:
        """Owner: set a user's access level, chat or code."""
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            pending[_pkey(message)] = "level"
            await reply(message, i18n.t("level.prompt", lang))
            return
        await _do_level(message, arg)

    @router.callback_query(F.data.startswith("setlvl:"))
    async def on_level_pick(cb: CallbackQuery) -> None:
        """Apply a chat or code level choice (owner-only)."""
        lang = _lang(cb)
        uid = cb.from_user.id if cb.from_user else None
        if uid != settings.owner_id:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.owner_only_access", lang))
            return
        try:
            _, target, lvl = (cb.data or "").split(":", 2)
        except ValueError:
            await cb.answer()
            return
        if lvl not in VALID_MODES:
            await cb.answer()
            return
        if allowlist.set_level(target, lvl):
            txt = i18n.t("level.set", lang, val=markup.escape_html(target), level=lvl)
        else:
            txt = i18n.t("level.not_found", lang, val=markup.escape_html(target))
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(cb.message, txt)
        with contextlib.suppress(Exception):
            await cb.answer()

    async def _do_expire(message: Message, arg: str) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        toks = arg.split()
        if len(toks) < 2:
            await reply(message, i18n.t("expire.usage", lang))
            return
        target = toks[0]
        if toks[1].lower() in ("never", "none", "off"):
            exp: str | None = None
        else:
            exp = normalize_date(toks[1])
            if exp is None:
                await reply(message, i18n.t("expire.bad_date", lang))
                return
        if not allowlist.set_expiry(target, exp):
            await reply(message, i18n.t("expire.not_found", lang, val=markup.escape_html(target)))
            return
        if exp:
            await reply(message, i18n.t("expire.set", lang, val=markup.escape_html(target), date=markup.escape_html(exp)))
        else:
            await reply(message, i18n.t("expire.cleared", lang, val=markup.escape_html(target)))

    @router.message(Command("expire"))
    async def cmd_expire(message: Message) -> None:
        """Owner: set or clear a user's access expiry."""
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            pending[_pkey(message)] = "expire"
            await reply(message, i18n.t("expire.prompt", lang))
            return
        await _do_expire(message, arg)

    async def _do_limit(message: Message, arg: str) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        # Limit sets a rolling-window cap (day or week).
        # - Syntax: /limit <id|@user> <tokens> [day|week] | off
        toks = arg.split()
        if len(toks) < 2:
            await reply(message, i18n.t("limit.usage", lang))
            return
        target = toks[0]
        amt = toks[1].lower()
        window = toks[2].lower() if len(toks) > 2 else "day"
        if amt in ("off", "none", "unlimited"):
            if not allowlist.set_rate(target, day=None, week=None):
                await reply(message, i18n.t("limit.not_found", lang, val=markup.escape_html(target)))
                return
            await reply(message, i18n.t("limit.cleared", lang, val=markup.escape_html(target)))
            return
        if window not in ("day", "week"):
            await reply(message, i18n.t("limit.usage", lang))
            return
        n = _parse_token_amount(amt)
        if n is None:
            await reply(message, i18n.t("limit.bad", lang))
            return
        if not allowlist.set_rate(target, **{window: n}):
            await reply(message, i18n.t("limit.not_found", lang, val=markup.escape_html(target)))
            return
        await reply(message, i18n.t("limit.set", lang, val=markup.escape_html(target),
                                    n=_fmt_tokens(n), window=window))

    @router.message(Command("limit"))
    async def cmd_limit(message: Message) -> None:
        """Owner: set a user's rolling usage cap, or off.

        - enforced against weighted usage units, not raw tokens
        """
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            pending[_pkey(message)] = "limit"
            await reply(message, i18n.t("limit.prompt", lang))
            return
        await _do_limit(message, arg)

    def _who_label(fname, uname, fallback: str) -> str:
        """A user's display label: friendly name (bold), then `@username`.

        - `fallback` (HTML-safe) is used only when both are missing
        """
        bits = []
        if fname:
            bits.append(f"<b>{markup.escape_html(str(fname))}</b>")
        if uname:
            bits.append(f"@{markup.escape_html(str(uname))}")
        return " ".join(bits) if bits else fallback

    async def _users_text(snap: dict, lang: str) -> list[str]:
        """The `/users` summary lines for owner and each entry.

        - each has per-user usage (day, week, total)
        - shown whether or not limits are set
        - token column shows the rolling day and week caps
        """
        # Fetch all users' usage in one GROUP BY.
        # - breakdown returns a list; key it by uid
        tokens = {}
        with contextlib.suppress(Exception):
            tokens = {r["uid"]: r for r in await db.get_all_users_breakdown("raw")}

        def _usage_lines(uid):
            # NBSP-pad values so monospace columns align.
            def _w(v):
                return _rpad_mono(_fmt_tokens(v), 6)
            out = []
            tb = tokens.get(uid)
            if tb:
                out.append(i18n.t("users.entry_usage_tok", lang, day=_w(tb["day"]),
                                  week=_w(tb["week"]), total=_w(tb["total"])))
            return out

        def _user_meta(rec) -> str:
            """Build the trailing meta line for a user.

            - show 'exp' only when time-limited, 'caps' only when capped
            """
            parts = []
            exp = rec.get("expires_at")
            if exp:
                parts.append(i18n.t("users.meta_exp", lang, expiry=markup.escape_html(str(exp))))
            rate = rec.get("rate") or {}
            if rate.get("day") is not None or rate.get("week") is not None:
                parts.append(i18n.t("users.meta_caps", lang, quota=_fmt_caps(rate, lang)))
            return "".join(parts)

        owner_id = snap.get("owner_id")
        # Label is friendly name plus @username.
        # - owner's name lives in `owner_prefs`
        oprefs = snap.get("owner_prefs", {})
        owner_who = _who_label(oprefs.get("friendly_name"), oprefs.get("username"),
                               i18n.t("users.btn_owner_bare", lang))
        lines = [
            i18n.t("users.header", lang),
            i18n.t("users.owner_id", lang, who=owner_who),
        ]
        lines.extend(_usage_lines(owner_id))   # Owner uncapped but still shown
        entries = snap.get("entries", {})
        pending_u = snap.get("pending", {})
        if not entries and not pending_u:
            lines.append(i18n.t("users.none_entries", lang))
        for uid, rec in entries.items():
            # Name then @username; id only as last resort.
            who = _who_label(rec.get("friendly_name"), rec.get("username"),
                             f"<code>{uid}</code>")
            # Expiry and caps shown only when set.
            lines.append(i18n.t("users.entry", lang, who=who,
                                level=rec.get("level", "chat"), meta=_user_meta(rec)))
            lines.extend(_usage_lines(uid))
        for name, rec in pending_u.items():
            who = _who_label(rec.get("friendly_name"), name, f"@{markup.escape_html(name)}")
            lines.append(i18n.t("users.pending", lang, who=who,
                                level=rec.get("level", "chat"), meta=_user_meta(rec)))
            # Pending (un-pinned) users have no id, so no usage.
        return lines

    def _users_keyboard(snap: dict, lang: str) -> InlineKeyboardMarkup:
        """One tappable button per user, owner first.

        - opens that user's settings card
        - `callback_data` is a numeric id, or a username if pending
        """
        B = InlineKeyboardButton
        rows: list[list[InlineKeyboardButton]] = []
        owner_id = snap.get("owner_id")
        rows.append([B(text=i18n.t("users.btn_owner", lang), callback_data=f"usr:card:{owner_id}")])
        for uid, rec in snap.get("entries", {}).items():
            # Button label: friendly name, then @username, then id.
            # - plain text; button labels aren't HTML
            uname = rec.get("username")
            who = rec.get("friendly_name") or (f"@{uname}" if uname else str(uid))
            rows.append([B(
                text=i18n.t("users.btn_entry", lang, who=who, level=rec.get("level", "chat")),
                callback_data=f"usr:card:{uid}")])
        for name, rec in snap.get("pending", {}).items():
            who = rec.get("friendly_name") or f"@{name}"
            rows.append([B(
                text=i18n.t("users.btn_pending", lang, who=who, level=rec.get("level", "chat")),
                callback_data=f"usr:card:{name}")])
        rows.append([B(text=i18n.t("users.btn_add", lang), callback_data="usr:add"),
                     B(text=i18n.t("users.btn_stats", lang), callback_data="usr:stats")])
        rows.append([
            # Back returns to the unified `sx:` hub.
            B(text=i18n.t("settings.back_to", lang), callback_data="sx:tab:s"),
            B(text=i18n.t("btn.close", lang), callback_data="usr:close"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # Per-user card pickers open with Back, never flip in place.
    # - `which` is mem or eff
    _USER_BOOL_OPTS = {
        "mem": ("usercard.pick_memory", "global_memory"),
        "eff": ("usercard.pick_maxeffort", "allow_max_effort"),
    }

    def _user_bool_picker_kb(target: str, which: str, cur: bool, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        rows = [[
            B(text=("✓ " if cur else "") + i18n.onoff(True, lang),
              callback_data=f"usr:boptset:{target}:{which}:on"),
            B(text=("✓ " if not cur else "") + i18n.onoff(False, lang),
              callback_data=f"usr:boptset:{target}:{which}:off"),
        ]]
        rows.append([B(text=i18n.t("usercard.btn_back", lang), callback_data=f"usr:card:{target}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _user_level_picker_kb(target: str, cur: str, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        rows = [[
            B(text=("✓ " if cur == lvl else "") + lvl, callback_data=f"usr:loptset:{target}:{lvl}")
            for lvl in ("chat", "code")
        ]]
        rows.append([B(text=i18n.t("usercard.btn_back", lang), callback_data=f"usr:card:{target}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _render_user_card(target: str, lang: str):
        """Build `(text, keyboard)` for one user's settings card.

        - the owner card shows self-limit toggles only
        - level, expiry, access, name, remove are hidden for owner
        """
        B = InlineKeyboardButton
        d = allowlist.describe(target)
        if d is None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                B(text=i18n.t("usercard.btn_back", lang), callback_data="usr:list")]])
            return i18n.t("usercard.not_found", lang), kb
        is_owner = d["kind"] == "owner"
        # Identity: friendly name plus clickable Telegram profile link.
        # - link is real HTML; title is not re-escaped
        # - id is the final fallback
        uid_ = d.get("id")
        uname_ = d.get("username")
        fname = d.get("friendly_name")  # Owner-assigned alias
        if uname_:
            _u = markup.escape_html(str(uname_))
            link = f'<a href="https://t.me/{_u}">@{_u}</a>'
        elif uid_:
            link = f'<a href="tg://user?id={int(uid_)}">{int(uid_)}</a>'
        else:
            link = markup.escape_html(str(target))
        who = f"{markup.escape_html(str(fname))} {link}" if fname else link
        tid = d.get("id")
        bd = await db.get_user_breakdown(tid) if tid is not None else \
            {"day": 0, "week": 0, "total": 0, "requests": 0}
        # Day/week/total figures are tokens, matching the caps.
        ub = bd
        rate = d.get("rate") or {"day": None, "week": None}

        def cap(v):
            return i18n.t("users.unlimited", lang) if v is None else _fmt_tokens(v)

        idle_raw = await db.get_user_default(tid, "idle_ttl_min") if tid is not None else None

        def _idle_lbl(v):  # None default, 0 unlimited, N minutes
            if v is None:
                return i18n.t("usercard.idle_default", lang)
            return "∞" if int(v) <= 0 else f"{int(v)}m"

        def _ms_lbl(v):  # None default, 0 unlimited, N sessions
            if v is None:
                return i18n.t("usercard.sessions_default", lang)
            return "∞" if int(v) <= 0 else str(int(v))

        kind_label = (i18n.t("usercard.kind_owner", lang) if is_owner else
                      i18n.t("usercard.kind_pending", lang) if d["kind"] == "pending" else "")
        lines = [
            i18n.t("usercard.title", lang, who=who, kind=kind_label),  # who is pre-built HTML
            i18n.t("usercard.level", lang, level=d.get("level", "chat")),
            i18n.t("usercard.expiry", lang,
                   expiry=markup.escape_html(str(d.get("expires_at") or i18n.t("users.never", lang)))),
            i18n.t("usercard.rate", lang, day=cap(rate.get("day")), week=cap(rate.get("week"))),
            i18n.t("usercard.memory", lang, state=i18n.onoff(d.get("global_memory"), lang)),
            i18n.t("usercard.maxeffort", lang, state=i18n.onoff(d.get("allow_max_effort"), lang)),
            i18n.t("usercard.tools", lang, tools=_fmt_cap(d.get("tool_cap"), lang)),
            i18n.t("usercard.sessions", lang, val=_ms_lbl(d.get("max_sessions"))),
            i18n.t("usercard.usage", lang, day=_fmt_tokens(ub["day"]), week=_fmt_tokens(ub["week"]),
                   total=_fmt_tokens(ub["total"]), reqs=bd["requests"]),
        ]
        if d.get("global_memory") and not is_owner:
            lines.append(i18n.t("usercard.memory_warn", lang))
        if is_owner:
            lines.append(i18n.t("usercard.owner_note", lang))

        rows: list[list[InlineKeyboardButton]] = []
        mem_btn = B(text=i18n.t("usercard.btn_memory", lang, state=i18n.onoff(d.get("global_memory"), lang)),
                    callback_data=f"usr:bopt:{target}:mem")  # Opens On/Off picker
        # Idle-TTL is shown on every card.
        # - owner can set it to test the reaper
        idle_btn = B(text=i18n.t("usercard.btn_idle", lang, val=_idle_lbl(idle_raw)),
                     callback_data=f"usr:idle:{target}")
        ses_btn = B(text=i18n.t("usercard.btn_sessions", lang, val=_ms_lbl(d.get("max_sessions"))),
                    callback_data=f"usr:max:{target}")
        if is_owner:
            # Owner can self-impose per-user limits for testing.
            # - level, expiry, access, name, remove are hidden
            # - owner is always code and never expires
            rows.append([mem_btn,
                         B(text=i18n.t("usercard.btn_maxeffort", lang, state=i18n.onoff(d.get("allow_max_effort"), lang)),
                           callback_data=f"usr:bopt:{target}:eff")])
            rows.append([B(text=i18n.t("usercard.btn_tools", lang, val=_fmt_cap(d.get("tool_cap"), lang)),
                           callback_data=f"usr:tools:{target}"),
                         idle_btn])
            rows.append([B(text=i18n.t("usercard.btn_day", lang), callback_data=f"usr:rday:{target}"),
                         B(text=i18n.t("usercard.btn_week", lang), callback_data=f"usr:rweek:{target}"),
                         ses_btn])
            # Owner can set their own friendly name in `owner_prefs`.
            rows.append([B(text=i18n.t("usercard.btn_name", lang), callback_data=f"usr:name:{target}")])
            if rate.get("day") is not None or rate.get("week") is not None:
                rows.append([B(text=i18n.t("usercard.btn_clear_limits", lang), callback_data=f"usr:rclr:{target}")])
        else:
            nxt = "code" if d.get("level") == "chat" else "chat"
            rows.append([B(text=i18n.t("usercard.btn_level", lang, level=d.get("level", "chat"), next=nxt),
                           callback_data=f"usr:lopt:{target}"),
                         ses_btn])
            rows.append([mem_btn,
                         B(text=i18n.t("usercard.btn_maxeffort", lang, state=i18n.onoff(d.get("allow_max_effort"), lang)),
                           callback_data=f"usr:bopt:{target}:eff")])
            rows.append([B(text=i18n.t("usercard.btn_tools", lang, val=_fmt_cap(d.get("tool_cap"), lang)),
                           callback_data=f"usr:tools:{target}"),
                         B(text=i18n.t("usercard.btn_access", lang), callback_data=f"usr:acc:{target}")])
            rows.append([B(text=i18n.t("usercard.btn_name", lang), callback_data=f"usr:name:{target}"),
                         B(text=i18n.t("usercard.btn_expiry", lang), callback_data=f"usr:exp:{target}")])
            rows.append([B(text=i18n.t("usercard.btn_day", lang), callback_data=f"usr:rday:{target}"),
                         B(text=i18n.t("usercard.btn_week", lang), callback_data=f"usr:rweek:{target}"),
                         idle_btn])
            if rate.get("day") is not None or rate.get("week") is not None:
                rows.append([B(text=i18n.t("usercard.btn_clear_limits", lang), callback_data=f"usr:rclr:{target}")])
            rows.append([B(text=i18n.t("usercard.btn_remove", lang), callback_data=f"usr:del:{target}")])
        rows.append([B(text=i18n.t("usercard.btn_back", lang), callback_data="usr:list")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)

    async def _render_user_tools(target: str, lang: str):
        """Return `(text, keyboard)` for the per-user tool-cap sub-page.

        - toggles which tools this user may use
        - `cap=None` means every tool is allowed
        """
        B = InlineKeyboardButton
        d = allowlist.describe(target)
        # Owner can open its own tool-cap sub-page.
        if d is None:
            return await _render_user_card(target, lang)
        cap = d.get("tool_cap")
        allowed = set(cap) if cap is not None else set(ALL_TOOLS)
        who = f"@{d['username']}" if d.get("username") else str(d.get("id") or target)
        text = i18n.t("usercard.tools_header", lang, who=markup.escape_html(who))
        rows = [[B(text=("✅ " if t in allowed else "⬜ ") + t + " · " + _tool_scope_label(t, lang),
                   callback_data=f"usr:tcap:{target}:{t}")]
                for t in ALL_TOOLS]
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"usr:card:{target}")])
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    async def _render_user_access(target: str, lang: str):
        """Return `(text, keyboard)` for the per-user access-exceptions page.

        - one row per option: exception if set, else owner base
        - tapping opens a per-option picker
        """
        B = InlineKeyboardButton
        d = allowlist.describe(target)
        if d is None or d["kind"] == "owner":
            return await _render_user_card(target, lang)  # owner always has full access
        exc = d.get("access") or {}
        base = {}
        with contextlib.suppress(Exception):
            base = await db.get_access_overrides()
        who = f"@{d['username']}" if d.get("username") else str(d.get("id") or target)
        text = i18n.t("usercard.access_header", lang, who=markup.escape_html(who))
        rows = []
        for skey in ss.PAGE_ORDER:
            setting = ss.SETTINGS.get(skey)
            if setting is None:
                continue
            cur = ss._coerce_access(exc.get(skey))
            if cur is not None:
                val = _access_label(cur, lang)
            else:
                base_acc = ss._coerce_access(base.get(skey)) or \
                    ss.BASE_ACCESS_DEFAULTS.get(skey, ss.Access.DELEGATED)
                val = i18n.t("usercard.access_base", lang, val=_access_label(base_acc, lang))
            rows.append([B(text=f"{_setting_name(setting, lang)}: {val} ▸",
                           callback_data=f"usr:accopt:{target}:{skey}")])
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"usr:card:{target}")])
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    def _user_access_picker_kb(target: str, skey: str, lang: str) -> InlineKeyboardMarkup:
        """Per-option access picker on a user card.

        - choices: Base (clear), Delegated, Read-only, Hidden
        - Back returns to the user's access sub-page
        """
        B = InlineKeyboardButton
        opts = [("base", i18n.t("usercard.access_base_opt", lang)),
                ("delegated", _access_label(ss.Access.DELEGATED, lang)),
                ("readonly", _access_label(ss.Access.READONLY, lang)),
                ("hidden", _access_label(ss.Access.HIDDEN, lang))]
        btns = [B(text=lbl, callback_data=f"usr:accset:{target}:{skey}:{lv}") for lv, lbl in opts]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"usr:acc:{target}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data.startswith("req:"))
    async def on_access_request_cb(cb: CallbackQuery) -> None:
        """Owner taps Allow on an unknown-user access request.

        - grants chat or code access by the user's numeric id
        """
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            await cb.answer(i18n.t("common.owner_only_access", lang))
            return
        parts = (cb.data or "").split(":")
        verb = parts[1] if len(parts) > 1 else ""
        if verb in ("al", "ac") and len(parts) > 2:
            try:
                tuid = int(parts[2])
            except (TypeError, ValueError):
                await cb.answer()
                return
            level = "code" if verb == "ac" else "chat"
            # Skip a stale Allow for an already-known user.
            # - avoids silently re-setting an existing level
            # - point the owner to /users instead
            existing = allowlist.level_of(tuid, None)
            if existing is not None:
                if cb.message is not None:
                    with contextlib.suppress(Exception):
                        await cb.message.edit_text(
                            i18n.t("access.req_already", lang, id=tuid, level=existing),
                            parse_mode="HTML")
                await cb.answer(i18n.t("access.req_already_toast", lang, level=existing))
                return
            with contextlib.suppress(Exception):
                allowlist.add(str(tuid), level)
            if cb.message is not None:
                with contextlib.suppress(Exception):
                    await cb.message.edit_text(
                        i18n.t("access.req_granted", lang, id=tuid, level=level),
                        parse_mode="HTML")
            await cb.answer(i18n.t("access.req_granted_toast", lang, level=level))
            return
        await cb.answer()

    @router.message(Command("users"))
    async def cmd_users(message: Message) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        if message.from_user:  # learn owner's @username for label
            with contextlib.suppress(Exception):
                allowlist.note_owner_identity(message.from_user.id, message.from_user.username)
        snap = allowlist.snapshot()
        await _send_menu(
            message.chat.id, "\n".join(await _users_text(snap, lang)),
            _users_keyboard(snap, lang),
        )

    async def _do_whois(message: Message, arg: str) -> None:
        """Owner: map a user id to sessions, workdir, transcript.

        - read-only; never mutates
        """
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        try:
            uid = int((arg or "").strip())
        except ValueError:
            await reply(message, i18n.t("whois.bad_id", lang))
            return
        rows, total = await db.browse_threads(uid, limit=500)
        if not rows:
            await reply(message, i18n.t("whois.none", lang, uid=uid))
            return
        label = ""
        with contextlib.suppress(Exception):
            lvl = allowlist.level_of(uid, None)
            if lvl:
                label = i18n.t("whois.label", lang, level=markup.escape_html(str(lvl)))
        # Report count of listed rows, not total count.
        out = [i18n.t("whois.head", lang, uid=uid, n=len(rows), label=label)]
        for r in rows:
            tid = r["thread_id"]
            st = await db.get_thread(tid)
            pubid = db.session_pubid(tid)
            glyph = mode_glyph(st.mode if st else "chat")
            name = (st.name if st and st.name else "Untitled")
            cwd = (st.cwd if st else "") or ""
            status = i18n.t("whois.tx_none", lang)
            if cwd:
                # Use the shared encoder for the transcript dir.
                # - matches the ai-title reader and disk layout
                tdir = archive.live_transcript_dir(cwd)
                if tdir.is_dir() and any(tdir.glob("*.jsonl")):
                    status = i18n.t("whois.tx_live", lang)
                else:
                    arch = settings.base_workdir / "_archive" / str(uid)
                    if arch.is_dir() and any(arch.glob(f"{pubid}-*.tar.gz")):
                        status = i18n.t("whois.tx_archived", lang)
            out.append(i18n.t("whois.row", lang, glyph=glyph,
                              name=markup.escape_html(name), pubid=pubid,
                              status=status, cwd=markup.escape_html(cwd)))
        await reply(message, "\n".join(out))

    @router.message(Command("whois"))
    async def cmd_whois(message: Message) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        arg = _command_arg(message)
        if not arg:
            # No arg: prompt and consume the next message.
            pending[_pkey(message)] = "whois"
            await reply(message, i18n.t("whois.prompt", lang))
            return
        await _do_whois(message, arg)

    @router.callback_query(F.data.startswith("usr:"))
    async def on_user_cb(cb: CallbackQuery) -> None:
        """Handle per-user management card taps (owner-only).

        - mutations re-render the card in place
        - free-text values go through arg-capture
        """
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            await cb.answer(i18n.t("common.owner_only_access", lang))
            return
        with contextlib.suppress(Exception):  # learn owner's @username
            allowlist.note_owner_identity(cb.from_user.id, cb.from_user.username)
        try:
            parts = (cb.data or "").split(":", 2)
            verb = parts[1] if len(parts) > 1 else ""
            target = parts[2] if len(parts) > 2 else ""
            msg = cb.message
            if msg is None:
                await cb.answer()
                return
            if verb == "close":
                with contextlib.suppress(Exception):
                    await msg.delete()
                await cb.answer()
                return
            if verb == "add":
                # Add user: arg-capture reusing /allow's prompt path.
                pending[(msg.chat.id, thread_key(msg), cb.from_user.id)] = "allow"
                with contextlib.suppress(Exception):
                    await bot.send_message(msg.chat.id, i18n.t("allow.prompt", lang), parse_mode="HTML")
                await cb.answer()
                return
            if verb == "list":
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer()
                return
            if verb == "stats":
                # The stats button opens the per-user stats table.
                send_kwargs: dict = {}
                if msg.chat.type != "private" and msg.message_thread_id:
                    send_kwargs["message_thread_id"] = msg.message_thread_id
                await _send_userstats(msg.chat.id, send_kwargs, lang)
                await cb.answer()
                return
            if verb in ("exp", "rday", "rweek", "name", "idle", "max"):
                # Free-text value: capture the owner's next message.
                action = {"exp": "usrexp", "rday": "usrrday", "rweek": "usrrweek",
                          "name": "usrname", "idle": "usridle", "max": "usrmax"}[verb]
                pending[(msg.chat.id, thread_key(msg), cb.from_user.id)] = f"{action}:{target}"
                prompt = {"exp": "usercard.prompt_expiry", "rday": "usercard.prompt_day",
                          "rweek": "usercard.prompt_week", "name": "usercard.prompt_name",
                          "idle": "usercard.prompt_idle", "max": "usercard.prompt_sessions"}[verb]
                with contextlib.suppress(Exception):
                    await bot.send_message(msg.chat.id, i18n.t(prompt, lang), parse_mode="HTML")
                await cb.answer()
                return
            if verb == "tools":
                text, kb = await _render_user_tools(target, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer()
                return
            if verb == "tcap":
                # Target carries "<target>:<toolname>".
                tgt, _, tool = target.partition(":")
                d = allowlist.describe(tgt)
                # Owner may toggle its own tool cap.
                if d and tool in ALL_TOOLS:
                    cap = d.get("tool_cap")
                    allowed = set(cap) if cap is not None else set(ALL_TOOLS)
                    allowed.discard(tool) if tool in allowed else allowed.add(tool)
                    ordered = [t for t in ALL_TOOLS if t in allowed]
                    # Store None when all tools allowed.
                    # - a tool added later stays allowed
                    # - otherwise store the explicit allowed list
                    allowlist.set_tool_cap(tgt, None if set(ordered) == set(ALL_TOOLS) else ordered)
                text, kb = await _render_user_tools(tgt, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer()
                return
            if verb == "acc":
                # Per-user access-exceptions sub-page.
                text, kb = await _render_user_access(target, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer()
                return
            if verb == "accopt":
                # Open per-option access picker; target is "<target>:<option>".
                tgt, _, skey = target.partition(":")
                if skey not in ss.SETTINGS:
                    await cb.answer()
                    return
                setting = ss.SETTINGS[skey]
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg,
                        i18n.t("usercard.access_opt_title", lang,
                               name=_setting_name(setting, lang)),
                        _user_access_picker_kb(tgt, skey, lang))
                await cb.answer()
                return
            if verb == "accset":
                # Apply a per-user access exception.
                # - target is "<target>:<option>:<level>"
                bits = target.split(":")
                if len(bits) >= 3:
                    tgt, skey, level = bits[0], bits[1], bits[2]
                    if skey in ss.SETTINGS:
                        allowlist.set_access_exception(
                            tgt, skey, None if level == "base" else level)
                    text, kb = await _render_user_access(tgt, lang)
                    await _edit_menu(msg, text, kb)
                await cb.answer(i18n.t("settings.saved", lang))
                return
            if verb == "del":
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=i18n.t("usercard.btn_confirm_remove", lang),
                                          callback_data=f"usr:delok:{target}")],
                    [InlineKeyboardButton(text=i18n.t("usercard.btn_back", lang),
                                          callback_data=f"usr:card:{target}")],
                ])
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg, i18n.t("usercard.confirm_remove", lang,
                                    who=markup.escape_html(target)),
                        kb)
                await cb.answer()
                return
            if verb == "delok":
                allowlist.remove(target)
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer(i18n.t("common.deleted", lang))
                return
            # Bool/level settings open a picker, not flip in place.
            if verb == "bopt":
                tgt, _, which = target.partition(":")
                if which not in _USER_BOOL_OPTS:
                    await cb.answer()
                    return
                title_key, field = _USER_BOOL_OPTS[which]
                d = allowlist.describe(tgt) or {}
                cur = bool(d.get(field))
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, i18n.t("settings.v2_pick", lang,
                                                 name=i18n.t(title_key, lang)),
                                     _user_bool_picker_kb(tgt, which, cur, lang))
                await cb.answer()
                return
            if verb == "boptset":
                bits = target.split(":")
                if len(bits) >= 3 and bits[1] in _USER_BOOL_OPTS:
                    tgt, which, val = bits[0], bits[1], bits[2] == "on"
                    if which == "mem":
                        allowlist.set_global_memory(tgt, val)
                    else:
                        allowlist.set_allow_max_effort(tgt, val)
                    text, kb = await _render_user_card(tgt, lang)
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, text, kb)
                await cb.answer(i18n.t("settings.saved", lang))
                return
            if verb == "lopt":
                d = allowlist.describe(target) or {}
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, i18n.t("settings.v2_pick", lang,
                                                 name=i18n.t("usercard.pick_level", lang)),
                                     _user_level_picker_kb(target, d.get("level", "chat"), lang))
                await cb.answer()
                return
            if verb == "loptset":
                tgt, _, level = target.partition(":")
                if level in ("chat", "code"):
                    allowlist.set_level(tgt, level)
                text, kb = await _render_user_card(tgt, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)
                await cb.answer(i18n.t("settings.saved", lang))
                return
            # In-place actions re-render the card afterwards.
            if verb == "rclr":
                allowlist.set_rate(target, day=None, week=None)
            text, kb = await _render_user_card(target, lang)
            with contextlib.suppress(Exception):
                await _edit_menu(msg, text, kb)
            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", lang))

    async def _apply_user_value(message: Message, action: str, text: str) -> None:
        """Apply an arg-captured user-card value, then re-post the card.

        - `action` is `usrexp`, `usrrday`, `usrrweek`, or `usrname`, each with `:<t>`
        """
        lang = _lang(message)
        if not _is_owner(message):
            return
        kind, _, target = action.partition(":")
        raw = text.strip()
        if kind == "usrname":
            # '-', off, none, clear wipe the alias; else set.
            allowlist.set_friendly_name(target, raw)
        elif kind == "usrexp":
            if raw.lower() in ("never", "none", "off"):
                allowlist.set_expiry(target, None)
            else:
                exp = normalize_date(raw)
                if exp is None:
                    await reply(message, i18n.t("expire.bad_date", lang))
                    return
                allowlist.set_expiry(target, exp)
        elif kind in ("usrrday", "usrrweek"):
            window = "day" if kind == "usrrday" else "week"
            # '0' sets a zero-token deny-all cap, not a clear.
            # - clear with off, none, or unlimited
            if raw.lower() in ("off", "none", "unlimited"):
                allowlist.set_rate(target, **{window: None})
            else:
                n = _parse_token_amount(raw)
                if n is None:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                allowlist.set_rate(target, **{window: n})
        elif kind == "usridle":
            # Idle-TTL in minutes.
            # - off/none/inf/never/0 means never reap
            # - default/clear unsets, using the server default
            # - otherwise a positive integer
            # - stored per uid, so it works for the owner
            d = allowlist.describe(target)
            tid = d.get("id") if d else None
            if tid is None:
                await reply(message, i18n.t("usercard.not_found", lang))
                return
            low = raw.lower()
            if low in ("default", "clear", "reset", "-"):
                await db.set_user_default(tid, "idle_ttl_min", None)
            elif low in ("off", "none", "inf", "infinite", "∞", "never", "unlimited", "0"):
                await db.set_user_default(tid, "idle_ttl_min", 0)
            else:
                try:
                    minutes = int(raw)
                except ValueError:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                if minutes < 1:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                await db.set_user_default(tid, "idle_ttl_min", minutes)
        elif kind == "usrmax":
            # Per-user session-count cap.
            # - default/clear/- inherits the global default
            # - off/none/unlimited/0 means unlimited
            # - otherwise a positive integer
            low = raw.lower()
            if low in ("default", "clear", "reset", "-"):
                allowlist.set_max_sessions(target, None)
            elif low in ("off", "none", "unlimited", "0"):
                allowlist.set_max_sessions(target, 0)
            else:
                try:
                    n = int(raw)
                except ValueError:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                if n < 1:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                allowlist.set_max_sessions(target, n)
        card_text, kb = await _render_user_card(target, lang)
        await _send_menu(message.chat.id, card_text, kb)  # Native rich user card

    async def _set_global_session_limit(message: Message, text: str) -> None:
        """Owner sets the global default per-user session limit.

        - applies to users without a per-user override
        - off, none, unlimited, or 0 means unlimited
        """
        lang = _lang(message)
        if not _is_owner(message):
            return
        low = text.strip().lower()
        if low in ("off", "none", "unlimited", "0"):
            await db.set_kv("max_sessions_default", "0")
            await reply(message, i18n.t("admin.gsl_saved", lang, val="∞"))
            return
        try:
            n = int(text.strip())
        except ValueError:
            await reply(message, i18n.t("limit.bad", lang))
            return
        if n < 1:
            await reply(message, i18n.t("limit.bad", lang))
            return
        await db.set_kv("max_sessions_default", str(n))
        await reply(message, i18n.t("admin.gsl_saved", lang, val=str(n)))

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        state = await _ensure_state(message)
        key = await _session_key(message)

        # Refresh account usage so /status shows live percentages.
        # - best-effort
        with contextlib.suppress(Exception):
            await sessions.refresh_account_usage()

        try:
            st = sessions.status(key) or {}
        except Exception:
            st = {}

        mode = st.get("mode") or state.mode
        model = st.get("model") or state.model
        cwd = st.get("cwd") or state.cwd
        busy = bool(st.get("busy", False))
        queued = int(st.get("queued", 0) or 0)
        cache_left = st.get("cache_seconds_left", 0) or 0
        rate = st.get("rate")

        # Unset defaults to `acceptEdits`.
        perm_name = PERM_MODE_TO_NAME.get(state.permission_mode or "acceptEdits", "auto-edits")
        usage_mode = getattr(sessions, "usage_mode", "footer")

        lang = _lang(message)
        sess_name = state.name or ("General" if key == 0 else f"#{abs(key)}")
        lines: list[str] = [
            "<h3>" + i18n.t("status.header", lang, glyph=mode_glyph(str(mode)),
                            name=markup.escape_html(sess_name)
                            + (" [shell]" if getattr(state, "shell_mode", False) else ""),
                            mode=i18n.mode_word(str(mode), lang),
                            sid=db.session_pubid(key)) + "</h3>",
        ]
        lines.append(i18n.t("status.model", lang, model=markup.escape_html(str(model))))
        if mode == "code":
            lines.append(i18n.t("status.directory", lang, cwd=markup.escape_html(str(cwd))))
            lines.append(i18n.t("status.permissions", lang, perm=markup.escape_html(perm_name)))
        lines.append(i18n.t("status.usage_display", lang, usage=markup.escape_html(str(usage_mode))))
        # Session flags render as a native checklist.
        _chk = lambda on: " checked" if on else ""  # noqa: E731
        lines.append(
            "<ul>"
            f'<li><input type="checkbox"{_chk(busy)}> '
            f'{markup.escape_html(i18n.t("status.chk_busy", lang, queued=queued))}</li>'
            "</ul>"
        )
        lines.append(i18n.t("status.cache", lang, secs=int(cache_left)))

        # Usage windows as a native list, one item per window.
        # - falls back to the latest per-thread snapshot
        rbt = getattr(sessions, "rate_by_type", {}) or {}
        win_items = []
        with contextlib.suppress(Exception):
            # Show every window the API reported.
            for _wk, _info in usage.ordered_windows(rbt):
                _s = usage.window_str(_info, lang)
                if _s:
                    win_items.append(_s)
        if win_items:
            lines.append("")
            lines.append("<b>" + i18n.t("usage.pinned_header", lang) + "</b>")
            lines.append("<ul>" + "".join(f"<li>{s}</li>" for s in win_items) + "</ul>")
        elif rate is not None:
            rate_str = _format_rate(rate, lang)
            if rate_str:
                lines.append("")
                lines.append(i18n.t("status.limits_header", lang))
                lines.append(rate_str)

        # Small utilization trend per window, when history exists.
        trend_lines: list[str] = []
        for rl_type, label in (("five_hour", "5h"), ("seven_day", "7d")):
            try:
                hist = await db.get_rate_history(rl_type, limit=12)
            except Exception:
                hist = []
            spark = _sparkline([h["utilization"] for h in hist])
            if spark:
                last = next(
                    (h["utilization"] for h in reversed(hist)
                     if isinstance(h["utilization"], (int, float))),
                    None,
                )
                tail = f" {last * 100:.0f}%" if isinstance(last, (int, float)) else ""
                trend_lines.append(f"{label}: <code>{spark}</code>{tail}")
        if trend_lines:
            lines.append("")
            lines.append("<b>" + i18n.t("status.trend_header", lang) + "</b>")
            lines.append("<ul>" + "".join(f"<li>{t}</li>" for t in trend_lines) + "</ul>")

        # Per-session usage totals as a native list.
        try:
            totals = await db.get_usage_totals(key)
        except Exception:
            totals = None
        if totals:
            cost = totals.get("cost", 0.0) or 0.0
            lines.append("")
            lines.append("<b>" + i18n.t("status.totals_header", lang) + "</b>")
            lines.append(
                "<ul>"
                f'<li>{i18n.t("status.requests", lang, n=totals.get("requests", 0))}</li>'
                f'<li>{i18n.t("status.tokens", lang, inp=_fmt_tokens(totals.get("input", 0)), out=_fmt_tokens(totals.get("output", 0)))}</li>'
                f'<li>{i18n.t("status.cache_tokens", lang, read=_fmt_tokens(totals.get("cache_read", 0)), created=_fmt_tokens(totals.get("cache_creation", 0)))}</li>'
                f'<li>{i18n.t("status.cost", lang, cost=f"{cost:.4f}")}</li>'
                "</ul>"
            )

        # Render /status as a native rich message.
        await reply_rich_html(message, "\n".join(lines))

    @router.message(Command("context"))
    async def cmd_context(message: Message) -> None:
        """Show the live session's context-window token usage, best effort."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        try:
            info = await sessions.context_usage(key)
        except Exception as exc:
            await reply(
                message,
                i18n.t("context.read_error", lang, err=markup.escape_html(str(exc))),
            )
            return

        if info is None:
            await reply(message, i18n.t("context.no_session", lang))
            return

        # Format defensively: the SDK shape varies.
        # - ContextUsageResponse is a TypedDict; legacy objects tolerated
        # - prefer SDK percentage, else derive from used/total
        # - never raise; fall back to a compact string
        used = _cu(info, "totalTokens", "used_tokens", "used")
        total = _cu(info, "maxTokens", "total_tokens", "total")
        pct = _cu(info, "percentage")

        lines = [i18n.t("context.header", lang)]
        shown = False
        if used is not None:
            lines.append(i18n.t("context.used", lang, n=_fmt_tokens(used)))
            shown = True
        if total is not None:
            lines.append(i18n.t("context.total", lang, n=_fmt_tokens(total)))
            shown = True
        try:
            if pct is not None:
                lines.append(i18n.t("context.usage", lang, pct=f"{float(pct):.0f}"))
                shown = True
            elif used is not None and total is not None and float(total) > 0:
                derived = float(used) / float(total) * 100
                lines.append(i18n.t("context.usage", lang, pct=f"{derived:.0f}"))
                shown = True
        except (TypeError, ValueError):
            pass

        if not shown:
            lines.append(f"<code>{markup.escape_html(str(info))}</code>")

        await reply(message, "\n".join(lines))

    @router.message(Command("limits"))
    async def cmd_limits(message: Message) -> None:
        """Show the caller's own rolling usage limits.

        - the owner instead sees real account subscription usage
        - a delegated user never sees account-wide numbers
        """
        await _ensure_state(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None

        if _is_owner(message):
            # Owner sees real account usage, refreshed live.
            with contextlib.suppress(Exception):
                await sessions.refresh_account_usage()
            body = usage.pinned_text(getattr(sessions, "rate_by_type", {}) or {}, lang)
            if body:
                await reply(message, i18n.t("limits.account_header", lang) + "\n" + body)
            else:
                await reply(message, i18n.t("limits.account_empty", lang))
            return

        # Delegated users see trailing 5h and 7d use vs cap.
        # - request count comes from the raw breakdown
        bd = await db.get_user_breakdown(uid)      # tokens plus request count
        ub = bd
        caps = allowlist.rate_of(uid, uname)

        def _row(label: str, used: int, cap) -> str:
            if cap:
                pct = min(100, int(used * 100 / cap)) if cap else 0
                bar = usage._bar(used / cap if cap else 0.0)
                return (f"{label}: <b>{_fmt_tokens(used)}</b> / "
                        f"{_fmt_tokens(cap)} ({pct}%) {bar}")
            return (f"{label}: <b>{_fmt_tokens(used)}</b> "
                    f"({i18n.t('limits.no_cap', lang)})")

        scap = await _effective_max_sessions(uid, uname)
        _, scount = await db.browse_threads(uid, limit=1)
        scap_lbl = i18n.t("limits.unlimited_word", lang) if scap <= 0 else str(scap)
        lines = [
            i18n.t("limits.header", lang),
            _row(i18n.t("limits.today", lang), ub["day"], caps.get("day")),
            _row(i18n.t("limits.week", lang), ub["week"], caps.get("week")),
            f"{i18n.t('limits.requests', lang)}: <b>{bd['requests']}</b>",
            i18n.t("limits.sessions", lang, used=scount, cap=scap_lbl),
            i18n.t("limits.rolling_note", lang),
        ]
        await reply(message, "\n".join(lines))

    async def _send_userstats(chat_id: int, send_kwargs: dict, lang: str) -> None:
        """Send the per-user usage dashboard as a native table.

        - one row per user: tokens for 5h, week, lifetime
        - plus requests and last-seen
        - falls back to a monospace grid if the send fails
        """
        rows = await db.get_all_users_breakdown("raw")   # Raw tokens per DM user
        if not rows:
            with contextlib.suppress(Exception):
                await bot.send_message(chat_id, i18n.t("userstats.empty", lang),
                                       parse_mode="HTML", **send_kwargs)
            return
        # Map uid to plain-text label; the table escapes.
        # - friendly name only, id as fallback
        # - owner resolved from `owner_prefs`
        def _plain_who(fname, uname, fallback: str) -> str:
            return str(fname) if fname else fallback

        labels: dict[int, str] = {}
        with contextlib.suppress(Exception):
            snap = allowlist.snapshot()
            for sid, rec in (snap.get("entries") or {}).items():
                try:
                    luid = int(sid)
                except (TypeError, ValueError):
                    continue
                labels[luid] = _plain_who(rec.get("friendly_name"), rec.get("username"), str(luid))
            oprefs = snap.get("owner_prefs", {})
            labels[settings.owner_id] = _plain_who(
                oprefs.get("friendly_name"), oprefs.get("username"), str(settings.owner_id))
        now = time.time()

        def _ago(ts: float) -> str:
            if not ts:
                return "—"
            d = max(0, now - ts)
            if d < 3600:
                return f"{int(d // 60)}m"
            if d < 86400:
                return f"{int(d // 3600)}h"
            return f"{int(d // 86400)}d"

        # Tokens per window: User, 5h, Wk, Tot, req, last.
        header = [
            i18n.t("userstats.col_user", lang),
            i18n.t("userstats.col_5h_tok", lang),
            i18n.t("userstats.col_wk_tok", lang),
            i18n.t("userstats.col_tot_tok", lang),
            i18n.t("userstats.col_req", lang), i18n.t("userstats.col_last", lang),
        ]
        trows = [header]
        for r in rows:
            uid = r["uid"]
            label = labels.get(uid, str(uid))
            if uid == settings.owner_id:
                label = f"👑 {label}"
            trows.append([
                label,
                _fmt_tokens(r["day"]),
                _fmt_tokens(r["week"]),
                _fmt_tokens(r["total"]),
                str(r["requests"]), _ago(r["last_ts"]),
            ])
        aligns = ["left", "right", "right", "right", "right", "right"]
        title = f"<b>👥 {markup.escape_html(i18n.t('userstats.title', lang))}</b>"
        legend = f"<i>{markup.escape_html(i18n.t('userstats.legend', lang))}</i>"
        html = title + "\n" + legend + markup.table_to_rich_html(trows, aligns)
        try:
            await bot(SendRichMessage(
                chat_id=chat_id, rich_message={"html": html}, **send_kwargs))
        except Exception:
            esc = [[markup.escape_html(c) for c in row] for row in trows]
            with contextlib.suppress(Exception):
                await bot.send_message(
                    chat_id, legend + "\n" + markup._render_table_pre(esc),
                    parse_mode="HTML", **send_kwargs)

    @router.message(Command("userstats"))
    async def cmd_userstats(message: Message) -> None:
        """Owner-only per-user usage dashboard (native table)."""
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        if message.from_user:  # learn owner's @username for label
            with contextlib.suppress(Exception):
                allowlist.note_owner_identity(message.from_user.id, message.from_user.username)
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        await _send_userstats(message.chat.id, send_kwargs, lang)

    @router.message(Command("test"))
    async def cmd_test(message: Message) -> None:
        """Owner-only self-test simulating a streamed generation.

        - paragraphs, a wide table, an asm snippet, an SVG diagram
        - lets live rich-draft formatting be eyeballed
        - the SVG is rasterized to a PNG at finish
        """
        if not _is_owner(message):
            return
        await sessions.stream_demo(message.chat.id)

    async def _recap_messages(key: int, lang: str) -> list[str]:
        """Build a session's last exchange as ready-to-send HTML messages.

        - reply rendered via `md_to_html`; prompt escaped verbatim
        - long replies split into size-safe chunks, never across a tag
        - the transcript table is separate from the SDK's resumed memory
        """
        try:
            msgs = await db.get_recent_messages(key, limit=8)
        except Exception:
            msgs = []
        if not msgs:
            st = await db.get_thread(key)
            has_ctx = bool(st and (st.code_session_id or st.chat_session_id))
            return [i18n.t("recap.empty_has_context" if has_ctx else "recap.empty", lang)]
        last_user = next((m for m in reversed(msgs) if m["role"] == "user"), None)
        last_asst = next((m for m in reversed(msgs) if m["role"] == "assistant"), None)
        head = [i18n.t("recap.header", lang)]
        if last_user:
            ut = last_user["text"]
            uclip = ut[:900] + (" …" if len(ut) > 900 else "")
            head.append(f"\n{i18n.t('recap.you', lang)}\n{markup.escape_html(uclip)}")
        footnote = i18n.t("recap.footnote", lang)
        if not last_asst:
            return ["\n".join(head + [f"\n{footnote}"])]
        at = last_asst["text"]
        aclip = at[:2500] + (" …" if len(at) > 2500 else "")
        head.append(f"\n{i18n.t('recap.claude', lang)}")
        header_block = "\n".join(head)
        one = f"{header_block}\n{markup.md_to_html(aclip)}\n\n{footnote}"
        if len(one) <= markup.HARD_LIMIT:
            return [one]
        out = [header_block]
        for raw in markup.split_markdown(aclip, limit=markup.SAFE_LIMIT):
            for html in markup.render_within_limit(raw):
                if not markup.is_empty_render(html):
                    out.append(html)
        out.append(footnote)
        return out

    @router.message(Command("last"))
    async def cmd_last(message: Message) -> None:
        """Show the last exchange verbatim: last prompt and reply."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        for chunk in await _recap_messages(key, lang):
            await reply(message, chunk)

    @router.message(Command("recap"))
    async def cmd_recap(message: Message) -> None:
        """Generate a one-line AI recap of the current session.

        - runs a model turn via the access gate and `_submit`
        - the verbatim last exchange is `/last`
        """
        await _ensure_state(message)
        lang = _lang(message)
        # Recap the current session, without idle rotation.
        # - no logged turns: point at /sessions
        # - avoids a confused "never talked" recap
        key = await _session_key(message)
        try:
            msgs = await db.get_recent_messages(key, limit=1)
        except Exception:
            msgs = []
        if not msgs:
            await reply(message, i18n.t("recap.empty_session", lang))
            return
        await _submit(message, i18n.t("recap.prompt", lang), key=key)

    async def _history_doc(key: int, lang: str):
        """Build a session's transcript as a Markdown document.

        - returns `(document, None)` or `(None, note)` if nothing to export
        - also used by the sessions Export action
        """
        try:
            msgs = await db.get_recent_messages(key, limit=2000)
        except Exception:
            msgs = []
        if not msgs:
            st = await db.get_thread(key)
            has_ctx = bool(st and (st.code_session_id or st.chat_session_id))
            return None, i18n.t("recap.empty_has_context" if has_ctx else "recap.empty", lang)
        state = await db.get_thread(key)
        name = (state.name if state else None) or (
            "General" if key == 0 else f"session {abs(key)}"
        )
        out = [f"# {i18n.t('history.title', lang, name=name)}", ""]
        for m in msgs:
            try:
                ts = f"{datetime.fromtimestamp(float(m['ts'])):%Y-%m-%d %H:%M}"
            except (TypeError, ValueError, OSError, OverflowError):
                ts = "?"
            who = i18n.t("history.you", lang) if m["role"] == "user" else i18n.t("history.claude", lang)
            out.append(f"## {who} · {ts}\n\n{m['text']}\n")
        try:
            return markup.as_document("\n".join(out), "transcript.md"), None
        except Exception as exc:
            return None, i18n.t("history.export_error", lang, err=markup.escape_html(str(exc)))

    @router.message(Command("history"))
    async def cmd_history(message: Message) -> None:
        """Export this session's conversation transcript as a Markdown file."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        doc, note = await _history_doc(key, lang)
        if doc is None:
            await reply(message, note)
            return
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        try:
            await bot.send_document(chat_id=message.chat.id, document=doc, **send_kwargs)
        except Exception as exc:
            await reply(
                message,
                i18n.t("history.export_error", lang, err=markup.escape_html(str(exc))),
            )

    @router.message(Command("rename"))
    async def cmd_rename(message: Message) -> None:
        """Rename the current session (DM) or forum topic (supergroup)."""
        await _ensure_state(message)
        lang = _lang(message)
        name = _command_arg(message)
        if name:
            await _do_rename(message, name)
            return
        if message.chat.type != "private" and not message.message_thread_id:
            await reply(message, i18n.t("topic.not_a_topic_rename", lang))
            return
        pending[_pkey(message)] = "rename"
        await reply(message, i18n.t("session.rename_prompt", lang))

    @router.message(Command("close"))
    async def cmd_close(message: Message) -> None:
        """Close the current forum topic (real topics only).

        - supergroup support is paused; DM-only for now
        """
        await _ensure_state(message)
        lang = _lang(message)
        await reply(message, i18n.t("topic.disabled", lang))
        return

    # A message sent mid-reply is handed to the running turn.
    # - no bot-side queue to manage

    @router.callback_query(F.data.startswith("stop:"))
    async def on_stop_cb(cb: CallbackQuery) -> None:
        """Inline Stop button on the per-turn control message: graceful stop."""
        try:
            lang = _lang(cb)
            parts = (cb.data or "").split(":")
            tid = int(parts[1]) if len(parts) > 1 else 0
            # Only the tapper's own DM session may be stopped.
            # - a forged callback_data must not interrupt others
            st = await db.get_thread(tid)
            if tid >= 0 or st is None or st.chat_id != cb.from_user.id:
                await cb.answer()
                return
            stopped = await sessions.stop(tid)
            await cb.answer(i18n.t("stopbtn.stopping" if stopped else "stopbtn.nothing", lang))
            if cb.message is not None:
                if stopped:
                    # Grey out the button for instant feedback.
                    # - streamer removes the control message after the turn
                    with contextlib.suppress(Exception):
                        await cb.message.edit_reply_markup(reply_markup=None)
                else:
                    # Nothing to stop: likely an orphaned control message.
                    # - a bot restart leaves a dead Stop button
                    # - delete the stale message
                    with contextlib.suppress(Exception):
                        await cb.message.delete()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    @router.message(Command("retry"))
    async def cmd_retry(message: Message) -> None:
        """Re-run the last prompt sent in this session."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        try:
            ok = await sessions.retry(message.chat.id, key)
        except Exception as exc:
            await reply(
                message,
                i18n.t("retry.error", lang, err=markup.escape_html(str(exc))),
            )
            return
        if ok:
            await reply(message, i18n.t("retry.ok", lang))
        else:
            await reply(message, i18n.t("retry.nothing", lang))

    # ---- plain text ----

    async def _access_block(uid: int | None, uname: str | None, lang: str, key: int) -> str | None:
        """Pre-turn access gate.

        - returns an i18n denial string if the turn is blocked
        - denied: chat-level user in a code session, or over quota
        - the owner is exempt
        - takes the identity directly so callbacks can gate turns too
        """
        uid = uid or 0
        st = await db.get_thread(key)
        if st is not None and st.mode == "code" and allowlist.level_of(uid, uname) != "code":
            return i18n.t("access.code_denied", lang)
        # Effort gate is enforced per turn.
        # - a revoked max-effort permission downgrades a stored max
        # - handle_text then rebuilds the session
        # - owner is exempt
        if st is not None and st.effort == "max" and not _may_max_effort(uid, uname):
            # Level under max for this model.
            await db.set_effort(key, models.effort_below_max(st.model or settings.default_model))
        # Rolling-window rate limits deny at the cap.
        # - trailing 5h or 7d tokens (input + output)
        # - windows derive from usage timestamps, so self-freeing
        # - 5h matches Anthropic's reset cadence
        # - legacy lifetime token grant is not enforced
        rate = allowlist.rate_of(uid, uname)
        now = time.time()
        day_cap = rate.get("day")
        if day_cap is not None:
            used = await db.get_user_usage_window(uid, since=now - db.SHORT_WINDOW_SEC)
            if used >= day_cap:
                return i18n.t("access.rate_day_exceeded", lang,
                              used=_fmt_tokens(used), cap=_fmt_tokens(day_cap))
        week_cap = rate.get("week")
        if week_cap is not None:
            used = await db.get_user_usage_window(uid, since=now - db.WEEK_WINDOW_SEC)
            if used >= week_cap:
                return i18n.t("access.rate_week_exceeded", lang,
                              used=_fmt_tokens(used), cap=_fmt_tokens(week_cap))
        return None

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        """Route a plain text message into the thread's Claude session."""
        # Ignore the bot's own messages defensively.
        if message.from_user is not None and message.from_user.is_bot:
            return
        text = (message.text or "").strip()
        if not text:
            return
        # Consume this message as a pending command argument.
        # - instead of routing it to the model
        action = pending.pop(_pkey(message), None)
        if action:
            await _run_pending(action, message, text)
            return
        key = await _session_key_for_turn(message)  # may start fresh session on idle
        # Delivery lag since Telegram stamped the message.
        # - tells whether client or server held it
        # - messages sent during a draft wait until final
        with contextlib.suppress(Exception):
            log.info("thread %s: message reached the bot %.1f s after Telegram stamped it",
                     key, time.time() - message.date.timestamp())
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        block = await _access_block(uid, uname, _lang(message), key)
        if block:
            await reply(message, block)
            return
        try:
            status = await sessions.handle_text(message.chat.id, key, text)
            await _ack_queue(message, status, _lang(message))
        except Exception as exc:
            await reply(
                message,
                i18n.t("text.process_error", _lang(message), err=markup.escape_html(str(exc))),
            )

    # ---- attachments ----

    async def _ack_queue(message: Message, status: int, lang: str) -> None:
        """Surface queued or full status of a submitted prompt.

        - silent when the prompt started immediately
        - a positive status is the number of prompts waiting
        - `SUBMIT_QUEUE_FULL` means it was rejected
        - best-effort: a failed ack must not break the turn
        """
        try:
            if status == _sessions.SUBMIT_QUEUE_FULL:
                await reply(message, i18n.t("queue.full_reject", lang,
                                            n=_sessions.MAX_QUEUED_MESSAGES))
            # A message behind a running reply is silent.
            # - folded into the turn or runs right after
        except Exception:
            pass

    async def _submit(message: Message, text: str, attachments=None, key: int | None = None,
                      gated: bool = False) -> None:
        """Route a turn (text plus optional blocks) into the session.

        - a conversational turn resolves its key via `_session_key_for_turn`, possibly rotating
        - an explicit `key` targets the current session without rotating
        - `gated=True` skips the re-check when the caller already ran `_access_block`
        """
        if key is None:
            key = await _session_key_for_turn(message)
        if not gated:
            uid = message.from_user.id if message.from_user else 0
            uname = message.from_user.username if message.from_user else None
            block = await _access_block(uid, uname, _lang(message), key)
            if block:
                await reply(message, block)
                return
        try:
            status = await sessions.handle_text(
                message.chat.id, key, text, attachments=attachments
            )
            await _ack_queue(message, status, _lang(message))
        except Exception as exc:
            await reply(
                message,
                i18n.t("attach.process_error", _lang(message), err=markup.escape_html(str(exc))),
            )

    async def _route_attachment(message, caption, blocks, inline, default_key, lang):
        """Send one attachment item to the model.

        - standalone items submit their own turn
        - album items (`media_group_id`) are buffered, then submitted as one turn
        """
        mgid = getattr(message, "media_group_id", None)
        if not mgid:
            header = caption or i18n.t(default_key, lang)
            text = f"{header}\n\n{inline}" if inline else header
            await _submit(message, text, blocks or None)
            return
        # Album: do the only await before touching the buffer.
        # - keeps get-or-create atomic across concurrent handlers
        skey = await _session_key(message)
        key = (message.chat.id, skey, mgid)
        buf = album_buf.get(key)
        if buf is None:
            buf = {"parts": [], "caption": "", "msg": message, "lang": lang,
                   "default_key": default_key, "timer": None, "dropped": 0}
            album_buf[key] = buf
        if caption and not buf["caption"]:
            buf["caption"] = caption
        if len(buf["parts"]) >= MAX_ALBUM_ITEMS:
            buf["dropped"] += 1
        else:
            buf["parts"].append((message.message_id, {"blocks": blocks, "inline": inline}))
        if buf["timer"] is not None:
            buf["timer"].cancel()
        buf["timer"] = asyncio.create_task(_album_after(key))

    async def _album_after(key):
        """Debounce timer body: flush the album when items stop.

        - cancelled and replaced by each new item in the group
        """
        try:
            await asyncio.sleep(ALBUM_DEBOUNCE_SECS)
        except asyncio.CancelledError:
            return
        await _flush_album(key)

    async def _flush_album(key):
        """Combine buffered album items into a single turn.

        - image and PDF blocks concatenated
        - text and code joined under one caption header
        """
        buf = album_buf.pop(key, None)
        if buf is None or not buf["parts"]:
            return
        lang = buf["lang"]
        header = buf["caption"] or i18n.t(buf["default_key"], lang)
        text, blocks = _combine_album_parts(
            buf["parts"], header, i18n.t("attach.truncated", lang))
        if buf["dropped"]:
            text += "\n\n" + i18n.t("attach.album_dropped", lang, n=buf["dropped"])
        await _submit(buf["msg"], text, blocks or None)

    async def _download(downloadable, limit: int, file_size: int | None, lang: str = "en"):
        """Download a Telegram file to bytes.

        - returns `(bytes, None)` or `(None, user_message)`
        - the message covers too-large or unreadable files
        """
        mb = limit // (1024 * 1024)
        if file_size and file_size > limit:
            return None, i18n.t("attach.too_large", lang, mb=mb)
        try:
            buf = await bot.download(downloadable)
            data = buf.read() if buf is not None else b""
        except Exception as exc:
            return None, i18n.t("attach.download_error", lang, err=markup.escape_html(str(exc)))
        if not data:
            return None, i18n.t("attach.read_error", lang)
        if len(data) > limit:
            return None, i18n.t("attach.too_large", lang, mb=mb)
        return data, None

    @router.message(F.photo)
    async def on_photo(message: Message) -> None:
        """Convert a Telegram photo to an image content block (JPEG)."""
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        photo = message.photo[-1]  # largest available size
        data, err = await _download(
            photo, MAX_IMAGE_BYTES, getattr(photo, "file_size", None), lang
        )
        if err:
            await reply(message, err)
            return
        b64 = base64.b64encode(data).decode("ascii")
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        }
        caption = (message.caption or "").strip()
        # Route through the album coalescer.
        await _route_attachment(message, caption, [block], "", "attach.default_image_prompt", lang)

    @router.message(F.document)
    async def on_document(message: Message) -> None:
        """Convert a file attachment to a block or inlined text.

        - images and PDFs go to the model as content blocks
        - UTF-8 text or code files are inlined into the prompt
        - anything else is rejected with a hint
        """
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        doc = message.document
        mime = (getattr(doc, "mime_type", "") or "").lower()
        fname = getattr(doc, "file_name", None) or "file"
        size = getattr(doc, "file_size", None)
        caption = (message.caption or "").strip()

        # Image sent as an uncompressed file.
        if mime.startswith("image/"):
            if mime not in ALLOWED_IMAGE_TYPES:
                await reply(message, i18n.t("attach.bad_image", lang))
                return
            data, err = await _download(doc, MAX_IMAGE_BYTES, size, lang)
            if err:
                await reply(message, err)
                return
            b64 = base64.b64encode(data).decode("ascii")
            block = {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            }
            await _route_attachment(message, caption, [block], "",
                                    "attach.default_image_prompt", lang)
            return

        # PDF becomes a native document block.
        if mime == "application/pdf" or fname.lower().endswith(".pdf"):
            data, err = await _download(doc, MAX_PDF_BYTES, size, lang)
            if err:
                await reply(message, err)
                return
            b64 = base64.b64encode(data).decode("ascii")
            block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            }
            await _route_attachment(message, caption, [block], "",
                                    "attach.default_doc_prompt", lang)
            return

        # Text/code file: inline the decoded content.
        data, err = await _download(doc, MAX_TEXT_BYTES, size, lang)
        if err:
            await reply(message, err)
            return
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            await reply(message, i18n.t("attach.bad_file", lang))
            return
        note = ""
        if len(content) > MAX_TEXT_INLINE_CHARS:
            content = content[:MAX_TEXT_INLINE_CHARS]
            note = f"\n\n{i18n.t('attach.truncated', lang)}"
        # Pass file body as an inline segment.
        # - lets the album coalescer join files under one caption
        inline = f"--- {fname} ---\n{content}{note}"
        await _route_attachment(message, caption, None, inline,
                                "attach.default_doc_prompt", lang)

    @router.message(F.voice)
    async def on_voice(message: Message) -> None:
        """Transcribe a voice note locally; route like typed text.

        - ffmpeg and faster-whisper run in the host process
        - the recognised text is shown back before submitting
        - off unless `VOICE_TRANSCRIPTION` is set
        """
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        if not settings.voice_transcription:
            return  # Feature off by deployment: stay silent.
        if not transcribe.available():
            await reply(message, i18n.t("voice.disabled", lang))
            return
        voice = message.voice
        cap = settings.voice_max_seconds
        dur = getattr(voice, "duration", None)
        if cap and dur and dur > cap:
            await reply(message, i18n.t("voice.too_long", lang, sec=cap))
            return
        # A voice note may be a pending command argument.
        # - pop pending first; transcript becomes the argument
        # - restored below on a mis-hear
        action = pending.pop(_pkey(message), None)
        # Gate before download and transcription for real turns.
        # - stops quota-exhausted users burning the inference lock
        # - pending management actions skip the gate
        key = None
        if action is None:
            key = await _session_key_for_turn(message)   # may start fresh session on idle
            uid = message.from_user.id if message.from_user else 0
            uname = message.from_user.username if message.from_user else None
            block = await _access_block(uid, uname, lang, key)
            if block:
                await reply(message, block)
                return
        data, err = await _download(
            voice, MAX_VOICE_BYTES, getattr(voice, "file_size", None), lang
        )
        if err:
            if action is not None:
                # Keep the capture alive on failure.
                # - `setdefault` avoids clobbering a newer pending
                pending.setdefault(_pkey(message), action)
            await reply(message, err)
            return
        # Placeholder shown during transcription, then becomes the transcript.
        # - makes a bad transcription visible
        # - use `message.answer()`; `reply()` returns nothing
        holder = None
        try:
            # Keeps the placeholder in the originating forum topic.
            # - None and ignored in a DM
            holder = await message.answer(
                i18n.t("voice.transcribing", lang),
                message_thread_id=message.message_thread_id,
            )
        except Exception:
            holder = None
        fail_msg = i18n.t("voice.transcribe_failed", lang)
        try:
            text = await transcribe.transcribe(
                data,
                model=settings.voice_model,
                lang=settings.voice_lang,
                max_seconds=cap,                         # bound decoded audio too
                download_root=(settings.voice_model_path
                               or transcribe.default_model_root(str(settings.base_workdir))),
            )
        except transcribe.AudioTooLong:
            # Byte cap tripped: report too long, not failure.
            # - Telegram duration metadata may be absent
            text = ""
            fail_msg = i18n.t("voice.too_long", lang, sec=cap)
        except Exception as exc:  # ffmpeg, model, or decode failure
            log.warning("voice transcription failed: %s", exc)
            text = ""
        text = (text or "").strip()
        if not text:
            if action is not None:
                # Keep capture alive on failure; keep newer pending.
                pending.setdefault(_pkey(message), action)
            if holder is not None:
                try:
                    await holder.edit_text(fail_msg)
                    return
                except Exception:
                    pass
            await reply(message, fail_msg)
            return
        shown = i18n.t("voice.transcript_prefix", lang, text=markup.escape_html(text))
        if holder is not None:
            try:
                await holder.edit_text(shown, parse_mode="HTML")
            except Exception:
                await reply(message, shown)
        else:
            await reply(message, shown)
        # Captured argument runs its command; otherwise a turn.
        if action is not None:
            await _run_pending(action, message, text)
            return
        # Prefix a marker so the model knows it's voice.
        # - transcript may contain recognition errors
        # - on-screen bubble stays the clean transcript
        # - gate already ran, so skip the re-check in `_submit`
        await _submit(message, i18n.t("voice.model_note", lang, text=text), key=key, gated=True)

    @router.message(F.location | F.venue)
    async def on_location(message: Message) -> None:
        """Turn a user-shared location or venue into a map turn.

        - the model receives coordinates as an ordinary turn
        - a venue also carries a title and address
        - nothing is echoed back
        - only a live share's first fix is used
        """
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        # A venue carries both venue and location fields.
        # - prefer the venue point, else top-level location
        venue = message.venue
        loc = message.location or (venue.location if venue is not None else None)
        if loc is None:
            return
        # 5 decimals is about 1 m, and compact.
        lat = f"{loc.latitude:.5f}"
        lon = f"{loc.longitude:.5f}"
        if venue is not None:
            note = i18n.t("location.venue_model_note", lang, title=venue.title,
                          address=venue.address, lat=lat, lon=lon)
        else:
            note = i18n.t("location.model_note", lang, lat=lat, lon=lon)
        # `_submit` resolves the session key and runs the gate.
        # - key may rotate on idle
        await _submit(message, note)

    # ---- permission callbacks ----

    @router.callback_query(F.data.startswith("perm:"))
    async def on_perm_callback(callback_query: CallbackQuery) -> None:
        """Forward an inline-button decision to the `PermissionGate`.

        - only the owner may approve dangerous tools
        - a non-owner tap is acknowledged and ignored
        - the prompt stays open for the owner
        """
        user = callback_query.from_user
        if user is None or user.id != settings.owner_id:
            try:
                await callback_query.answer(i18n.t("permgate.owner_only", _lang(callback_query)))
            except Exception:
                pass
            return
        try:
            await gate.handle_decision(callback_query)
        except Exception:
            # Never let a callback failure bubble up.
            try:
                await callback_query.answer(i18n.t("permgate.processing_error", _lang(callback_query)))
            except Exception:
                pass

    return router


# Settings menu: tap buttons instead of typing commands.
# - callback_data "st:<verb>:<args>" stays under 64 bytes


def _mark(name: str, current: str) -> str:
    """Button label with a check mark on the current option."""
    return f"✓ {name}" if name == current else name


# Generic registry-driven /settings UI.
# - tabs: session, defaults, global; role-gated
# - non-owners never see Global or owner-only rows
# - rows show resolved value plus source-scope badge
# - Tools grid and Users admin stay separate pages
_SCOPE_CODE = {ss.Scope.SESSION: "s", ss.Scope.USER: "u", ss.Scope.GLOBAL: "g"}
_CODE_SCOPE = {v: k for k, v in _SCOPE_CODE.items()}


def _scope_tab_key(scope) -> str:
    """i18n key for a scope tab's label."""
    return {
        ss.Scope.SESSION: "settings.tab_session",
        ss.Scope.USER: "settings.tab_user",
        ss.Scope.GLOBAL: "settings.tab_global",
    }[scope]


def _setting_name(setting, lang: str) -> str:
    """Bare display name of a registry setting.

    - drops the value placeholder and chevron from the row key
    """
    raw = i18n.t(setting.name_key, lang)
    # Drop trailing ": {placeholder}" and any " ▸" chevron.
    raw = re.sub(r":?\s*\{[^}]*\}\s*▸?\s*$", "", raw)
    return raw.rstrip(" ▸").strip()


def _scope_badge(scope, lang: str) -> str:
    """Short localized badge naming which scope supplies a value."""
    return i18n.t({
        ss.Scope.SESSION: "settings.badge_session",
        ss.Scope.USER: "settings.badge_user",
        ss.Scope.GLOBAL: "settings.badge_global",
    }[scope], lang)


def _setting_value_label(setting, value, lang: str, model: str | None = None) -> str:
    """Human label for a resolved setting value.

    - bool becomes on/off, model id becomes its alias
    - `None` becomes the localized default or unlimited
    - `model` is the effective model, used to name effort defaults
    """
    if value is None:
        if setting.key == "max_turns":
            return i18n.t("maxturns.unlimited", lang)
        if setting.key == "effort":
            return _effort_default_label(model, lang)
        return i18n.t("settings.val_default", lang)
    if setting.type is bool:
        return i18n.onoff(bool(value), lang)
    if setting.key == "model":
        return models.label(value)
    if setting.key == "permission_mode":
        return PERM_MODE_TO_NAME.get(value, value)
    if setting.key == "language":
        return i18n.lang_name(value)
    if setting.key == "effort":
        return _effort_label(value, lang)  # opportunistically translated CLI level
    return str(value)


def _setting_choice_labels(setting, lang: str,
                           model: str | None = None) -> list[tuple[str, str]]:
    """Return `[(callback_value, button_label)]` for a fixed-choice picker.

    - `model` is the effective model; effort lists its CLI levels
    """
    if setting.type is bool:
        # Booleans get an On/Off picker like other settings.
        # - opens a sub-menu with Back
        # - labels match `_setting_value_label`, so the check lands
        return [("on", i18n.onoff(True, lang)), ("off", i18n.onoff(False, lang))]
    if setting.key == "model":
        # Offer the model families the CLI currently reports.
        # - before any catalog, offer only the current model
        return [(v, models.label(v))
                for v in models.picker_values(fallback=(model,) if model else ())]
    if setting.key == "effort":
        # Offer the effort levels the CLI lists for this model.
        # - none for a model without effort
        return ([(lv, _effort_label(lv, lang)) for lv in models.effort_levels(model)]
                + [("default", _effort_default_label(model, lang))])
    if setting.key == "permission_mode":
        return [(PERM_MODE_TO_NAME.get(m, m), PERM_MODE_TO_NAME.get(m, m))
                for m in ("default", "acceptEdits", "plan", "bypassPermissions")]
    if setting.key == "language":
        return [(code, i18n.lang_name(code)) for code in i18n.LANGUAGES]
    if setting.key == "max_turns":
        # Free integer via /maxturns; hub offers presets and unlimited.
        return [("10", "10"), ("25", "25"), ("50", "50"), ("100", "100"),
                ("default", i18n.t("maxturns.unlimited", lang))]
    # Fallback: render the raw choices.
    return [(str(c), str(c)) for c in (setting.choices or ())]


def _ss_tools_keyboard(state, lang: str = "en") -> InlineKeyboardMarkup:
    """Per-session Tools grid with one toggle per tool.

    - chat shows web tools, code shows the full toolset
    - Back returns to the settings hub
    """
    B = InlineKeyboardButton
    mode = getattr(state, "mode", "chat") if state else "chat"
    universe = engine.CODE_TOOLS if mode == "code" else engine.CHAT_TOOLS
    enabled = getattr(state, "tools_enabled", None) if state else None
    enabled_set = set(enabled) if enabled is not None else set(universe)
    rows = [
        [B(text=("✅ " if t in enabled_set else "⬜ ") + t + " · " + _tool_scope_label(t, lang),
           callback_data=f"sx:tooltog:{t}")]
        for t in universe
    ]
    rows.append([B(text=i18n.t("btn.back", lang), callback_data="sx:tab:s")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ss_usage_keyboard(cur: str, lang: str = "en") -> InlineKeyboardMarkup:
    """Usage-display picker for the settings hub (owner only).

    - options: off, footer, pinned, both
    """
    B = InlineKeyboardButton
    btns = [B(text=_mark(m, cur), callback_data=f"sx:usageset:{m}")
            for m in ("off", "footer", "pinned", "both")]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
    rows.append([B(text=i18n.t("btn.back", lang), callback_data="sx:tab:s")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _access_label(access, lang: str = "en") -> str:
    """Localized label for an access level."""
    return i18n.t({
        ss.Access.DELEGATED: "settings.access_delegated",
        ss.Access.READONLY: "settings.access_readonly",
        ss.Access.HIDDEN: "settings.access_hidden",
    }[access], lang)


def _ss_option_admin_kb(setting, ctx, lang: str = "en") -> InlineKeyboardMarkup:
    """Owner page for one setting: global value and base access.

    - per-user exceptions live on the user card
    - Back returns to the Global tab
    """
    B = InlineKeyboardButton
    rows: list[list[InlineKeyboardButton]] = []
    if setting.set.get(ss.Scope.GLOBAL) is not None:
        gval, _ = ss.resolve_from(setting, ctx, ss.Scope.GLOBAL)
        vlabel = _setting_value_label(setting, gval, lang,  # Global scope sets the default model
                                      getattr(getattr(ctx, "settings", None), "default_model", None))
        cbv = (f"sx:tog:g:{setting.key}" if setting.type is bool
               else f"sx:nav:g:{setting.key}")
        rows.append([B(text=i18n.t("settings.opt_value", lang, val=vlabel), callback_data=cbv)])
    acc_label = _access_label(ss.configured_base_access(setting, ctx), lang)
    rows.append([B(text=i18n.t("settings.opt_access", lang, val=acc_label),
                   callback_data=f"sx:acc:{setting.key}")])
    rows.append([B(text=i18n.t("btn.back", lang), callback_data="sx:tab:g")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ss_access_kb(setting, ctx, lang: str = "en") -> InlineKeyboardMarkup:
    """Base-access picker for one option (owner only).

    - Back returns to the option admin page
    """
    B = InlineKeyboardButton
    cur = ss.configured_base_access(setting, ctx)
    btns = [B(text=_mark(_access_label(a, lang), _access_label(cur, lang)),
              callback_data=f"sx:accset:{setting.key}:{a.value}")
            for a in (ss.Access.DELEGATED, ss.Access.READONLY, ss.Access.HIDDEN)]
    rows = [btns]
    rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"sx:opt:{setting.key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values) -> str:
    """Render a unicode sparkline from utilization fractions (0..1).

    - non-numeric points are skipped
    - returns an empty string with fewer than 2 numeric points
    """
    nums = [v for v in (values or []) if isinstance(v, (int, float))]
    if len(nums) < 2:
        return ""
    out = []
    for v in nums:
        frac = min(1.0, max(0.0, float(v)))
        out.append(_SPARK_CHARS[min(len(_SPARK_CHARS) - 1, int(frac * (len(_SPARK_CHARS) - 1) + 0.5))])
    return "".join(out)


def _fmt_date(ts) -> str:
    """Format an epoch as YYYY-MM-DD, or "?"."""
    try:
        return f"{datetime.fromtimestamp(float(ts)):%Y-%m-%d}"
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def _rpad_mono(s: str, width: int) -> str:
    """Right-align `s` to `width` using NBSP padding.

    - the client may collapse ordinary spaces inside `<code>`
    - NBSP is preserved and one cell wide in monospace
    """
    return "\u00A0" * max(0, width - len(s)) + s


def _fmt_tokens(n) -> str:
    """Compact token count: 12345 becomes "12.3k".

    - values under 1000 are shown as-is
    - a trailing ".0" is dropped
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def _parse_token_amount(s: str):
    """Parse a human token amount like '500k' into an int.

    - returns `None` for anything not a non-negative number
    - underscores, commas, and spaces are ignored
    """
    s = (s or "").strip().lower().replace("_", "").replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("k"):
        mult, s = 1000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        val = float(s) * mult
    except ValueError:
        return None
    return int(val) if val >= 0 else None


def _fmt_caps(rate, lang: str = "en") -> str:
    """Compact rolling-cap display for per-user views.

    - the unlimited glyph when uncapped, else 'd:500k w:2m'
    """
    rate = rate or {}
    parts = []
    if rate.get("day") is not None:
        parts.append("d:" + _fmt_tokens(rate["day"]))
    if rate.get("week") is not None:
        parts.append("w:" + _fmt_tokens(rate["week"]))
    return " ".join(parts) if parts else i18n.t("users.unlimited", lang)


# Full per-user tool-cap universe, in stable order.
# - every tool usable across chat and code
# - owner toggles which a user may use
ALL_TOOLS: list[str] = list(engine.CHAT_TOOLS) + [
    t for t in engine.CODE_TOOLS if t not in engine.CHAT_TOOLS
]


def _fmt_cap(cap, lang: str = "en") -> str:
    """Tool-cap summary for the per-user card.

    - localized 'all' when uncapped (`None`), else 'N/total'
    """
    if cap is None:
        return i18n.t("usercard.cap_all", lang)
    return f"{len(cap)}/{len(ALL_TOOLS)}"


def _tool_scope_label(tool: str, lang: str = "en") -> str:
    """Session types a tool applies to, shown on its toggle.

    - web tools: chat and code; the rest code only
    """
    return i18n.t("tool.scope_both" if tool in engine.CHAT_TOOLS else "tool.scope_code", lang)


def _cu(obj: object, *names: str):
    """Read the first present field from a dict or object.

    - SDK returns a TypedDict; `getattr` alone misses keys
    - returns the first non-`None` value, else `None`
    """
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _format_rate(rate: object, lang: str = "en") -> str:
    """Render a `RateLimitInfo` snapshot as a compact localized status line.

    - tolerates missing attributes; returns an empty string if nothing useful
    """
    rtype = getattr(rate, "rate_limit_type", None)
    util = getattr(rate, "utilization", None)
    status = getattr(rate, "status", None)
    resets_at = getattr(rate, "resets_at", None)

    parts: list[str] = []
    if rtype:
        parts.append(i18n.t("status.rate_type", lang, val=markup.escape_html(str(rtype))))
    if status:
        parts.append(i18n.t("status.rate_status", lang, val=markup.escape_html(str(status))))
    if util is not None:
        try:
            parts.append(i18n.t("status.rate_util", lang, val=f"{float(util) * 100:.0f}"))
        except (TypeError, ValueError):
            pass
    if resets_at:
        try:
            local = datetime.fromtimestamp(int(resets_at))
            parts.append(i18n.t("status.rate_resets", lang, val=f"{local:%Y-%m-%d %H:%M:%S}"))
        except (TypeError, ValueError, OSError, OverflowError):
            pass

    if not parts:
        return ""
    return "; ".join(parts)
