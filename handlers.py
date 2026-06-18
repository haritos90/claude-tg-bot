"""aiogram Router: all commands, plain-text routing, and permission callbacks.

This is the Telegram-facing control surface of the bot. Every update reaching
these handlers has already passed the access middleware (owner + allowlist), so
non-owner-gated handlers are open to any allowed user. User-facing strings are
English; code/comments are English too.

Per-topic isolation: each forum topic is identified by message_thread_id; the
General topic (no thread id) is represented by the integer key 0. The helper
thread_key() collapses None -> 0. When sending into a topic we must pass
message_thread_id=None for key 0 and the key otherwise; reply() handles this.

Note: the bot is now DM-first — each user's sessions are negative-keyed DM
sessions in a private chat. The supergroup/forum-Topics path below (positive
keys, message_thread_id routing) is frozen/dormant; it is kept but not the live
mode (see AGENTS.md §5).
"""

from __future__ import annotations

import base64
import contextlib
import inspect
import io
import re
# import shutil  # unused after #177 — session-delete teardown moved to archive.py
import time
import zipfile
from pathlib import Path
from datetime import datetime

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest  # #173: detect "not modified" on rich edits
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

import archive
import commands
import db
import engine
import i18n
import markup
import settings_schema as ss
import usage
from allowlist import normalize_date
from rich_message import EditRichMessage, SendRichMessage  # #164/#173: native rich


# Friendly aliases mapped to concrete model ids for the /model command.
MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}
# Reverse map so the settings menu can show a friendly alias for a stored id.
MODEL_ID_TO_ALIAS: dict[str, str] = {v: k for k, v in MODEL_ALIASES.items()}

# The two session types. A session's type is FIXED at creation (no switching).
VALID_MODES = ("chat", "code")

# Reasoning-effort levels accepted by /effort (SDK EffortLevel literals, #23).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def mode_glyph(mode: str) -> str:
    """The visual marker for a session type — used everywhere a session is shown
    so chat and code sessions are always told apart at a glance. Code uses a big
    green square (terminal-like), chat a speech bubble (owner request 2026-06-15;
    was the ▸ shell-prompt caret of #96)."""
    return "🟩" if mode == "code" else "💬"


def mode_tagline(mode: str, cwd: str | None = None, lang: str = "en") -> str:
    """One-line description of what a session of this type does (HTML)."""
    if mode == "code":
        # #203: the workdir path is an internal detail the user never interacts with,
        # so it is no longer appended to session descriptions (card / options / mode /
        # created / upgraded). `cwd` stays in the signature for callers/compat.
        # was (replaced for #203):
        #   where = (i18n.t("mode.tagline_where", lang, cwd=markup.escape_html(cwd))
        #            if cwd else "")
        where = ""
        return i18n.t("mode.tagline_code", lang, glyph=mode_glyph("code"), where=where)
    return i18n.t("mode.tagline_chat", lang, glyph=mode_glyph("chat"))

# Valid usage display modes for /usage.
VALID_USAGE_MODES = ("off", "footer", "pinned", "both")

# Attachments. Anthropic accepts these media types as image content blocks;
# Telegram photos are always JPEG, an image sent as a file carries its own mime.
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Raw-size caps before base64 (Anthropic: ~5 MB/image, ~32 MB request for PDFs).
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 1 * 1024 * 1024
# A text/code file is inlined into the prompt; cap the characters so a huge file
# cannot blow up the context window.
MAX_TEXT_INLINE_CHARS = 200_000

# Friendly /permissions names <-> SDK permission_mode values (code mode only).
# Per-name help text lives in the l10n table under "perm.help.<name>".
PERM_NAME_TO_MODE: dict[str, str] = {
    "ask": "default",
    "auto-edits": "acceptEdits",
    "plan": "plan",
    "full-access": "bypassPermissions",
}
PERM_MODE_TO_NAME: dict[str, str] = {v: k for k, v in PERM_NAME_TO_MODE.items()}


# Commands advertised to Telegram via setMyCommands, ordered MOST-USED FIRST so
# the menu reads top-to-bottom by how often you reach for each one. Everything in
# the menu is discoverable by tapping it — no need to remember typed commands.
#
# #139: names + descriptions + scope now live in ONE place — commands.py (the
# COMMANDS registry). These module-level lists are DERIVED from it so they can't
# drift across languages or surfaces. The literal arrays below are commented out
# (kept for audit/revert); replaced by commands.menu_slugs()/code_slugs()/
# owner_slugs(). Descriptions come from Cmd.label[lang], not the cmd.* i18n rows.
#
# was — replaced for #139:
# _COMMAND_NAMES: list[str] = [
#     "new", "sessions", "settings", "rename",
#     "status", "code", "chat", "clear",
#     "recap", "history", "files", "export",
#     "fork", "maxturns", "context", "queue", "clearqueue", "retry",
#     "help", "whoami",
# ]
# _OWNER_COMMAND_NAMES: list[str] = ["auto", "allow", "deny", "users", "level", "expire", "limit", "sandbox"]
# _CODE_COMMAND_NAMES: list[str] = ["code", "files", "export", "permissions", "maxturns"]
_COMMAND_NAMES: list[str] = commands.menu_slugs()
_OWNER_COMMAND_NAMES: list[str] = commands.owner_slugs()
_CODE_COMMAND_NAMES: list[str] = commands.code_slugs()


def _chat_command_names() -> list[str]:
    """The command set a chat-level user sees (all but the code-mode-only ones)."""
    return [n for n in _COMMAND_NAMES if n not in _CODE_COMMAND_NAMES]


def _build_commands(names: list[str], lang: str) -> list[BotCommand]:
    """Build a BotCommand list with descriptions in the given locale.

    #139: the description is now sourced from the COMMANDS registry
    (Cmd.label[lang]), the single source of truth, rather than the cmd.* i18n
    rows. Falls back to English if a locale is somehow absent.
    """
    # was — replaced for #139 (cmd.* i18n lookup):
    # return [BotCommand(command=name, description=i18n.t(f"cmd.{name}", lang)) for name in names]
    by = commands.by_slug()
    out: list[BotCommand] = []
    for name in names:
        cmd = by.get(name)
        desc = cmd.label.get(lang) or cmd.label["en"] if cmd else name
        out.append(BotCommand(command=name, description=desc))
    return out


async def setup_commands(bot, owner_id: int | None = None) -> None:
    """Register the bot's command list with Telegram (setMyCommands).

    Registered once per supported locale via the ``language_code`` parameter so a
    Russian Telegram client sees a Russian menu and an English one sees English.
    The default (no language_code) scope falls back to English. The owner's
    private chat gets the shared menu PLUS the owner-only admin commands, so those
    never appear for anyone else. A scoped list REPLACES (not appends to) the
    default for that scope, so we send the combined list explicitly per locale.
    """
    # #139: fail loudly at startup if the command registry (commands.py) has
    # drifted from the live @router handlers or is missing a locale, so the
    # menu/help/handler surfaces can't silently diverge again.
    commands.assert_commands_consistent(languages=tuple(i18n.LANGUAGES))
    # Default scope (everyone except the owner): the CHAT-level set — code-mode-only
    # commands are omitted so a chat-only user doesn't see commands they can't use
    # (#102). The owner's private chat (below) overrides this with the full set.
    chat_names = _chat_command_names()
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
    """Return the isolation key for a message: real thread id, or 0 for General."""
    return message.message_thread_id or 0


def build_router(settings, sessions, gate, bot, allowlist) -> Router:
    """Build the aiogram Router wiring all commands, text, and callbacks.

    Args:
        settings: loaded Settings (bot_token, owner_id, default_model, ...).
        sessions: SessionManager orchestrating per-thread ClaudeSessions.
        gate: PermissionGate handling code-mode approval callbacks.
        bot: the aiogram Bot instance (used for create_forum_topic, etc.).
        allowlist: the Allowlist used by the owner-only access commands.
    """
    router = Router(name="main")

    async def reply(message: Message, text: str) -> None:
        """Send `text` (already Telegram HTML) back into the same topic.

        Command handlers author their own HTML directly (<b>, <code>, and values
        pre-escaped with markup.escape_html), so we send it AS-IS. We must NOT
        run it through md_to_html — that would HTML-escape the tags again and
        Telegram would show literal "<b>" / "&lt;". Long text is split; very long
        becomes a .md document. (Model output is rendered elsewhere, in Streamer.)
        """
        # Reply into the same place the message came from: a supergroup topic
        # keeps its message_thread_id; a private chat (DM) has no thread. We use
        # the message's own context here (NOT the session key) so DM sessions,
        # which use synthetic negative keys, still post to the user's chat.
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id

        # #172: send command replies as NATIVE rich messages too, so their look/font
        # matches /status, /userstats and the streamed answers (the owner flagged the
        # inconsistency). `text` is already valid Telegram HTML → use the html field;
        # rich messages also need no char-splitting. Fall back to the classic
        # doc/chunked path below on any failure, so a reply is never lost.
        try:
            await bot(SendRichMessage(chat_id=message.chat.id,
                                      rich_message={"html": text}, **send_kwargs))
            return
        except Exception:
            pass

        # Very long: send as a document rather than spamming chunks.
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
                # Fall through to chunked text on any document failure.
                pass

        # `text` is already valid Telegram HTML — send as-is, only splitting if
        # it exceeds the size limit (command replies are short, so this is
        # almost always a single chunk).
        for chunk in markup.split_message(text):
            if not chunk:
                continue
            try:
                await bot.send_message(
                    chat_id=message.chat.id,
                    text=chunk,
                    parse_mode="HTML",
                    **send_kwargs,
                )
            except Exception:
                # Last resort: deliver a fully-escaped plain version so content
                # is not lost if the HTML failed to parse.
                try:
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=markup.escape_html(chunk),
                        parse_mode="HTML",
                        **send_kwargs,
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------ helpers

    async def reply_rich_html(message: Message, html: str) -> None:
        """#170: send a READ-ONLY reply as a native rich message (sendRichMessage html)
        so headings, lists and checklists render. Falls back to the classic HTML
        reply() if the (new) API call fails — a reply is never lost."""
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        try:
            await bot(SendRichMessage(chat_id=message.chat.id,
                                      rich_message={"html": html}, **send_kwargs))
        except Exception:
            await reply(message, html)

    async def _send_menu(chat_id: int, text: str, kb=None, **send_kwargs):
        """#173: OPEN an inline-keyboard menu as a NATIVE rich message (sendRichMessage
        + reply_markup), so menu screens (settings hub, user cards, session menus)
        carry the same rich font as command replies and streamed answers — not the
        classic ``parse_mode="HTML"`` look. ``text`` is already valid Telegram HTML →
        the ``html`` rich field. Returns the sent Message (callers may need its id), or
        None if both the rich and the classic fallback send fail — so a menu is never
        lost even when the rich API rejects the payload."""
        # #202: rich-message HTML folds raw newlines (HTML whitespace collapsing),
        # which squashed multi-line menus (session list, cards) onto ONE line. Convert
        # \n → <br> for the rich html field; the classic fallback keeps the raw text
        # (parse_mode="HTML" renders \n as a newline and doesn't support <br>).
        # #209: assumes menu text carries no <pre>/preformatted blocks (none do today) —
        # revisit this substitution if a menu ever includes preformatted content.
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
        """#173: EDIT a menu in place as a NATIVE rich message (editMessageText +
        rich_message, Bot API 10.1) so the nav-edits keep the rich font instead of
        downgrading to classic HTML on every tap. An unchanged body ("message is not
        modified") is a no-op. Any other failure (e.g. the message was opened classic
        before this shipped, or the rich edit is rejected) falls back to the classic
        ``edit_text`` — preserving exactly the prior behaviour."""
        rich_html = text.replace("\n", "<br>")  # #202: see _send_menu (newline → <br>)
        try:
            await bot(EditRichMessage(chat_id=msg.chat.id, message_id=msg.message_id,
                                      rich_message={"html": rich_html}, reply_markup=kb))
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return  # identical content already on screen — nothing to do
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)

    async def _session_key(message: Message) -> int:
        """Resolve the session key for an incoming message.

        Supergroup → the forum topic id (0 for General). Private chat (DM) → the
        user's CURRENT bot-managed session, creating a default "Session 1" on first
        contact. DM sessions use synthetic NEGATIVE keys so they never collide with
        supergroup topics (>= 0) or another user's sessions — preserving the hard
        per-session isolation guarantee.
        """
        if message.chat.type == "private":
            uid = message.chat.id  # == the user id in a private chat
            cur = await db.get_dm_current(uid)
            # Heal a missing OR dangling pointer: on first contact (None), and when
            # the pointer references a deleted/missing row, re-point to the user's
            # most-recent real DM session (a negative key) or mint a fresh default.
            # Otherwise _ensure_state would resurrect an empty row at the stale key.
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
        """Resolve the session key a callback (menu tap) should act on.

        In a DM the menu message is the bot's, so we key by the TAPPER's current
        DM session, not the message context.
        """
        msg = cb.message
        if msg is not None and msg.chat.type == "private":
            cur = await db.get_dm_current(cb.from_user.id)
            return cur if cur is not None else 0
        return thread_key(msg) if msg is not None else 0

    def _command_arg(message: Message) -> str:
        """Return the text after the command word, stripped (may be empty)."""
        text = message.text or message.caption or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()

    def _is_owner(message: Message) -> bool:
        """True iff the message comes from the configured owner."""
        return bool(message.from_user) and message.from_user.id == settings.owner_id

    def _may_max_effort(uid: int | None, uname: str | None) -> bool:
        """Whether this user may select the (expensive) `max` reasoning effort — the
        owner (unless self-revoked for testing, #185), or a user explicitly granted it.
        Guests are blocked so they can't burn the owner's one shared subscription via
        max thinking (#120 / effort gate)."""
        # #185: route the owner through allow_max_effort_of too — it defaults the owner
        # to True, so default behaviour is unchanged, but an owner self-revoke now gates
        # the owner. was an unconditional owner pass:
        #   if uid is not None and uid == settings.owner_id: return True
        return bool(allowlist.allow_max_effort_of(uid, uname))

    def _lang(obj) -> str:
        """Resolve the acting user's interface locale (Message or CallbackQuery).

        Reads the per-user cache warmed by LanguageMiddleware; falls back to the
        default locale when the user is somehow unknown.
        """
        user = getattr(obj, "from_user", None)
        return i18n.cached_lang(getattr(user, "id", 0) or 0)

    async def _ensure_state(message: Message):
        """Ensure a ThreadState row exists for this session; return it.

        The default working directory is per-session: BASE_WORKDIR/<sid> (#140),
        so each session's code-mode work is isolated from every other session's
        files. (DM sessions are created by allocate_dm_session, which sets the same
        per-sid cwd; this path only fires for a brand-new key — e.g. a supergroup
        topic or General(0).)
        """
        key = await _session_key(message)
        # #140: name the per-session workdir by the stable public sid, not the raw
        # key. was: default_cwd = str(settings.base_workdir / str(key))
        # #181: nested layout — the session cwd is <sid>/work.
        default_cwd = str(settings.base_workdir / db.session_sid(key) / "work")
        return await db.ensure_thread(
            key, message.chat.id, settings.default_model, default_cwd
        )

    async def _rebuild_session(thread_id: int) -> bool:
        """Ask the SessionManager to drop/rebuild the in-memory session.

        After mode/model/cwd/permission changes the next message must use the
        new settings, which requires closing the old SDK client. SessionManager
        exposes a helper for this; we call whichever spelling exists and
        otherwise fall back to a full reset so settings still take effect.

        Returns True when the rebuild was DEFERRED because a turn is currently
        running (the change then applies once that run finishes); False otherwise.
        """
        helper = getattr(sessions, "on_mode_or_model_or_cwd_change", None)
        if callable(helper):
            try:
                return bool(await helper(thread_id))
            except Exception:
                pass
        # Fallback: a reset closes the client and drops the record so the next
        # message rebuilds from persisted state. (Loses in-memory session id,
        # but that is the safe, correct behaviour after a settings change.)
        try:
            await sessions.reset(thread_id)
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ settings

    @router.message(Command("tools"))
    async def cmd_tools(message: Message) -> None:
        """Open the per-session Tools page — toggle each tool on/off (#129/#141).
        Chat shows the web research tools; code shows the full agent toolset. Back
        returns to the unified /settings hub (the old st: tools page is retired)."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        try:
            state = await db.get_thread(key)
        except Exception:
            state = None
        try:
            await _send_menu(  # #173: native rich menu open
                message.chat.id, i18n.t("settings.tools_title", lang),
                _ss_tools_keyboard(state, lang),
            )
        except Exception as exc:
            await reply(message, i18n.t("settings.open_error", lang, err=markup.escape_html(str(exc))))

    @router.message(Command("settings"))
    async def cmd_settings(message: Message) -> None:
        """Open the unified, scope-tabbed settings hub for this session.

        #138/#141: /settings opens the REGISTRY-DRIVEN hub (This session / My
        defaults / Global) — see ``_send_ss_hub``. Model / Effort / Permissions /
        Max turns / Memory / Sandbox / Language are registry rows; Tools, Usage
        (owner) and Users (owner) are ``sx:`` sub-pages that return to this hub.
        The old flat ``st:`` hub is retired (``on_settings_cb`` is now a thin
        stale-button shim)."""
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
        """#141: the OLD flat settings hub is RETIRED — /settings now opens the
        registry-driven ``sx:`` hub, with Tools / Usage / Users ported onto it as
        sub-pages. This is a thin compatibility shim catching STALE ``st:`` buttons
        left in old chat messages: ``st:close`` deletes the menu; anything else
        bounces to the unified hub. The old flat-hub page builders (_settings_keyboard,
        _settings_text, _settings_apply, _gather_vals, _onoff_label) were DELETED in #214
        (dead since #141 — nothing live ever called them); this shim and _mark stay."""
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

    # ---------------------------------------------- generic settings v2 (#138)
    # The registry-driven, scope-tabbed /settings hub. It reuses the resolver +
    # role gate from settings_schema so visibility/edit are decided in ONE place,
    # and supersedes the bespoke per-setting wiring above where it maps cleanly.

    def _role_of(uid: int | None, uname: str | None) -> ss.Role:
        """The acting user's registry Role (owner / code / chat)."""
        is_owner = uid is not None and uid == settings.owner_id
        level = None if is_owner else allowlist.level_of(uid, uname)
        return ss.role_for(is_owner, level)

    async def _build_ss_ctx(key: int, uid: int | None, role: ss.Role) -> ss.Ctx:
        """Build a resolution Ctx for the bound session, preloading the USER-scope
        defaults (incl. the locale from its own kv store) AND the #151 access config
        (owner base overrides + this user's exceptions) so resolve()/effective_access()
        stay synchronous on the hot path."""
        try:
            state = await db.get_thread(key)
        except Exception:
            state = None
        user_defaults: dict = {}
        if uid is not None:
            for skey in ss.SETTINGS:
                with contextlib.suppress(Exception):
                    user_defaults[skey] = await db.get_user_default(uid, skey)
            # Language lives in its OWN kv store, not the generic user_default kv.
            with contextlib.suppress(Exception):
                lang_pref = await db.get_user_lang(uid)
                if lang_pref is not None:
                    user_defaults["language"] = lang_pref
        # #151: owner's per-option base-access overrides + this user's exceptions.
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
        """Scope tabs this role may see. Non-owners never get the Global tab."""
        tabs = [ss.Scope.SESSION, ss.Scope.USER]
        if role >= ss.Role.OWNER:
            tabs.append(ss.Scope.GLOBAL)
        return tabs

    def _ss_text(scope, role: ss.Role, lang: str) -> str:
        """Header for the active scope tab."""
        return i18n.t("settings.v2_header", lang,
                      tab=i18n.t(_scope_tab_key(scope), lang))

    def _ss_code_blocked(setting, scope, ctx: ss.Ctx) -> bool:
        """Hide a CODE-ONLY setting on the SESSION tab when the bound session is a
        chat (menu.md §1.7) — gated on the session MODE, not the user's level, so a
        code-level user in a chat session doesn't see Permissions / Max turns / Sandbox."""
        if scope != ss.Scope.SESSION or not ss.is_code_only(setting.key):
            return False
        return getattr(ctx.state, "mode", None) != "code"

    def _ss_hub_keyboard(scope, ctx: ss.Ctx, role: ss.Role, lang: str) -> InlineKeyboardMarkup:
        """Tabbed hub keyboard for the active scope: a tab row, then one row per
        visible setting (resolved value + source badge + control affordance), then
        the bespoke Tools page and the owner-only Usage / Users rows LAST (menu.md
        §1.8), then Close. All sub-pages are sx:-namespaced and return to this hub
        (#141/#142 — the old st: flat hub is retired)."""
        B = InlineKeyboardButton
        rows: list[list[InlineKeyboardButton]] = []
        # Tab row (mark the active tab).
        tab_row = []
        for sc in _visible_tabs(role):
            label = i18n.t(_scope_tab_key(sc), lang)
            tab_row.append(B(text=(f"• {label}" if sc == scope else label),
                             callback_data=f"sx:tab:{_SCOPE_CODE[sc]}"))
        rows.append(tab_row)
        # The GLOBAL tab is the owner's ACCESS-CONFIG surface (#151): it lists EVERY
        # registry option (so base access is settable for ALL of them, even ones with
        # no global VALUE scope like effort/max_turns). SESSION/USER list the options
        # storable at that scope.
        if scope == ss.Scope.GLOBAL:
            setting_list = [ss.SETTINGS[k] for k in ss.PAGE_ORDER
                            if k in ss.SETTINGS and ss.SETTINGS[k].can_view(role)]
        else:
            setting_list = ss.settings_for_scope(scope, role)
        # One row per visible setting at this scope.
        for setting in setting_list:
            # On SESSION/USER a setting needs a setter for this scope; the GLOBAL row
            # is the value/access admin page, so no per-scope setter is required.
            if scope != ss.Scope.GLOBAL and setting.set.get(scope) is None:
                continue
            # Code-only rows don't appear in a chat session (menu.md §1.7).
            if _ss_code_blocked(setting, scope, ctx):
                continue
            # #151 access model: HIDDEN settings don't appear; READ-ONLY show but
            # can't be changed; DELEGATED are fully editable. (Owner is always full;
            # the GLOBAL tab is owner-only so every option is visible there.)
            if scope != ss.Scope.GLOBAL and not ss.can_view_setting(setting, ctx):
                continue
            editable = ss.can_edit_setting(setting, ctx)
            # #138-fix: on the SESSION tab show the effective resolved value; on the
            # USER/GLOBAL tabs show what THAT scope contributes. For a non-editable
            # (read-only) setting the user's per-scope value doesn't count, so show
            # the access-aware effective value (global) instead (#151 soft-revoke).
            value, src = (ss.resolve_from(setting, ctx, scope) if editable
                          else ss.resolve_effective(setting, ctx))
            name = _setting_name(setting, lang)
            vlabel = _setting_value_label(setting, value, lang)
            badge = _scope_badge(src, lang)
            text = i18n.t("settings.v2_row", lang, name=name, val=vlabel, badge=badge)
            sc_code = _SCOPE_CODE[scope]
            if scope == ss.Scope.GLOBAL:
                # Owner Global tab: the row opens the option-admin page (global value
                # + base access + per-user exceptions) — menu.md §4.4 (#151).
                cb = f"sx:opt:{setting.key}"
            elif not editable:
                cb = f"sx:ro:{setting.key}"           # read-only → a "locked" toast
            elif setting.type is bool:
                cb = f"sx:tog:{sc_code}:{setting.key}"
            else:
                cb = f"sx:nav:{sc_code}:{setting.key}"
            rows.append([B(text=text, callback_data=cb)])
        # Bespoke pages (Tools grid / Usage picker / Users admin) are sx: sub-pages
        # linked from the SESSION tab only. Tools is code-only (menu.md §1.7); the
        # owner-only Usage + Users rows go LAST, above Close (menu.md §1.8).
        if scope == ss.Scope.SESSION:
            if getattr(ctx.state, "mode", None) == "code":
                rows.append([B(text=i18n.t("settings.row_tools", lang), callback_data="sx:tools")])
            if role >= ss.Role.OWNER:
                rows.append([B(text=i18n.t("settings.row_usage", lang,
                                           val=getattr(sessions, "usage_mode", "footer")),
                               callback_data="sx:usage")])
                rows.append([B(text=i18n.t("settings.row_users", lang), callback_data="sx:users")])
                # #178 + owner Admin hub: the Admin sub-page (archive retention,
                # global toggles, user-management launchers) sits LAST (menu.md §1.8).
                rows.append([B(text=i18n.t("settings.row_admin", lang), callback_data="sx:admin")])
        # #218: surface the owner Admin sub-page on the GLOBAL tab too. The global
        # session limit, archive retention and global toggles are account-wide config,
        # so the Global tab (the owner's global surface) is a natural home for it — not
        # only the Session tab. Same sx:admin page; no duplication of the controls.
        if scope == ss.Scope.GLOBAL and role >= ss.Role.OWNER:
            rows.append([B(text=i18n.t("settings.row_admin", lang), callback_data="sx:admin")])
        rows.append([B(text=i18n.t("btn.close", lang), callback_data="sx:close")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # ----------------------------------------------- owner Admin sub-page (#178)
    # Retention picker choices: (days, i18n_key). 0 = keep forever ("never").
    _RETENTION_CHOICES = (
        (30, "admin.ret_1mo"), (90, "admin.ret_3mo"), (180, "admin.ret_6mo"),
        (365, "admin.ret_12mo"), (0, "admin.ret_never"),
    )

    async def _archive_retention_days() -> int:
        """Effective archive retention in days: the owner's runtime value (kv
        ``archive_retention_days``, set here) if present, else the startup default
        (``settings.archive_retention_days``). 0 = keep forever."""
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
                           gsl: int = 10) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        gsl_lbl = "∞" if gsl <= 0 else str(gsl)
        rows = [
            [B(text=i18n.t("admin.retention", lang, val=_retention_label(ret_days, lang)),
               callback_data="sx:admin:ret"),
             B(text=i18n.t("admin.gsl_btn", lang, val=gsl_lbl), callback_data="sx:admin:gsl")],
            [B(text=i18n.t("admin.tog_codesplit", lang, val=i18n.onoff(cs_on, lang)),
               callback_data="sx:admin:tog:cs"),
             B(text=i18n.t("admin.tog_workingplate", lang, val=i18n.onoff(wp_on, lang)),
               callback_data="sx:admin:tog:wp")],
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
        with contextlib.suppress(Exception):
            await _edit_menu(msg, i18n.t("admin.title", lang),  # #173: native rich nav-edit
                             _ss_admin_keyboard(lang, days, cs, wp, gsl))

    def _ss_picker_keyboard(setting, scope, ctx: ss.Ctx, lang: str,
                            may_max: bool = True) -> InlineKeyboardMarkup:
        """Choice picker for one fixed-choice setting at a scope (#101 convention).
        ``may_max`` hides the gated `max` effort level from users not allowed it
        (the apply path still enforces it for a forged tap)."""
        B = InlineKeyboardButton
        # #138-fix: mark the value held at THIS scope (chain from it), not the
        # cross-scope resolved one, so the picker's ✓ matches the tab.
        value, _ = ss.resolve_from(setting, ctx, scope)
        cur_label = _setting_value_label(setting, value, lang)
        sc_code = _SCOPE_CODE[scope]
        choices = _setting_choice_labels(setting, lang)
        if setting.key == "effort" and not may_max:
            choices = [(v, lbl) for v, lbl in choices if v != "max"]
        # full-access (bypassPermissions) disarms the approval gate → OWNER-ONLY
        # (#150); hide it from non-owners (the apply path also rejects a forged tap).
        if setting.key == "permission_mode" and ctx.role < ss.Role.OWNER:
            choices = [(v, lbl) for v, lbl in choices if v not in ("full-access", "bypassPermissions")]
        btns = [B(text=_mark(label, cur_label),
                  callback_data=f"sx:set:{sc_code}:{setting.key}:{cbval}")
                for cbval, label in choices]
        rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"sx:tab:{sc_code}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _ss_apply(setting, scope, raw_val, ctx: ss.Ctx, role: ss.Role,
                        uid: int | None, uname: str | None, key: int) -> bool:
        """Apply a tap AFTER re-checking edit_role + scope authorization server-side.

        Returns True if the value was written. A guest/non-owner tapping an
        owner-only or global control (forged callback) is REJECTED here — the button
        is never authorization (#138, AGENTS §2)."""
        # 1. The setting must be editable by THIS user: the structural role gate AND
        #    the #151 access model (effective access == DELEGATED). A READ-ONLY/HIDDEN
        #    setting can't be written even by a forged callback (owner is always full).
        if not ss.can_edit_setting(setting, ctx):
            return False
        # 2. The GLOBAL scope is owner-only regardless of the setting's edit_role.
        if scope == ss.Scope.GLOBAL and role < ss.Role.OWNER:
            return False
        # 3. There must be a setter for this scope.
        setter = setting.set.get(scope)
        if setter is None:
            return False
        # 4. Per-setting extra gates that the role matrix alone doesn't cover.
        if setting.key == "effort" and raw_val == "max" and not _may_max_effort(uid, uname):
            return False
        # full-access (bypassPermissions) disarms the code-mode approval gate, so it
        # is OWNER-ONLY (AGENTS §2 / #150) — reject a forged tap from a code user.
        if (setting.key == "permission_mode"
                and raw_val in ("full-access", "bypassPermissions")
                and role < ss.Role.OWNER):
            return False
        # 5. Coerce the callback string into the stored value.
        value = _coerce_ss_value(setting, raw_val)
        # Setters may be sync (GLOBAL model/sandbox mutate config in-process) or
        # async (db writes) — await only when the call returned an awaitable.
        result = setter(ctx, value)
        if inspect.isawaitable(result):
            await result
        # Language has side effects (locale cache + per-chat menu); model/effort/etc.
        # need the live SDK client rebuilt for a SESSION change to take effect now.
        if setting.key == "language" and value:
            i18n.remember_lang(uid, value)
            with contextlib.suppress(Exception):
                await _apply_user_menu(uid, uid, uname, value)
        elif scope == ss.Scope.SESSION:
            await _rebuild_session(key)
        return True

    def _coerce_ss_value(setting, raw_val):
        """Map a picker/toggle callback token into the value the setter stores."""
        if setting.type is bool:
            return raw_val if isinstance(raw_val, bool) else (raw_val == "on")
        if setting.key == "model":
            return MODEL_ALIASES.get(raw_val, raw_val)
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
        """Render (or re-render) the tabbed hub at ``scope``."""
        role = _role_of(uid, uname)
        if scope not in _visible_tabs(role):
            scope = ss.Scope.SESSION  # bounce a forged/stale Global tab to session
        ctx = await _build_ss_ctx(key, uid, role)
        text = _ss_text(scope, role, lang)
        kb = _ss_hub_keyboard(scope, ctx, role, lang)
        if edit_msg is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(edit_msg, text, kb)  # #173: native rich nav-edit
            return
        await _send_menu(chat_id, text, kb)  # #173: native rich menu open

    async def _send_setting_picker(chat_id: int, key: int, uid: int | None,
                                   uname: str | None, lang: str, setting_key: str,
                                   scope=ss.Scope.SESSION) -> bool:
        """Open the hub PICKER for one registry setting as a NEW message (#145/#146).

        The slash commands (/model, /effort, /permissions, /maxturns, /language)
        are thin entry points to the SAME ``sx:`` picker, so there is ONE code path
        per setting — no separate pm:/pe:/lang: keyboards to drift. Returns False
        (so the caller can fall back) when the setting isn't viewable for this role
        or is code-only in a chat session."""
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
            await _send_menu(  # #173: native rich menu open
                chat_id,
                i18n.t("settings.v2_pick", lang, name=_setting_name(setting, lang)),
                kb)
        return True

    @router.callback_query(F.data.startswith("sx:"))
    async def on_settings_v2_cb(cb: CallbackQuery) -> None:
        """Drive the registry-based settings hub: tab switch / picker / apply."""
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

            if verb == "nav" and len(parts) >= 4:
                scope = _CODE_SCOPE.get(parts[2], ss.Scope.SESSION)
                setting = ss.SETTINGS.get(parts[3])
                # Gate: must be viewable, and the Global tab is owner-only.
                if (setting is None or not setting.can_view(role)
                        or (scope == ss.Scope.GLOBAL and role < ss.Role.OWNER)):
                    await cb.answer(i18n.t("common.error", lang))
                    return
                ctx = await _build_ss_ctx(key, uid, role)
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
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
                    # #138-fix: flip the value held at THIS scope (chain from it),
                    # so toggling on the "my defaults" tab doesn't invert a session
                    # override and write the result to the user-default scope.
                    value, _ = ss.resolve_from(setting, ctx, scope)
                    raw_val = not bool(value)  # flip the scope-local bool
                else:
                    raw_val = parts[4] if len(parts) > 4 else ""
                ok = await _ss_apply(setting, scope, raw_val, ctx, role, uid, uname, key)
                if not ok:
                    # Forged / unauthorized tap, or a gated choice (e.g. max effort).
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                lang = _lang(cb)  # a language change updates the acting locale
                await _send_ss_hub(msg.chat.id, key, uid, uname, lang, scope, edit_msg=msg)
                await cb.answer(i18n.t("settings.saved", lang))
                return

            # ---- bespoke sx: sub-pages (Tools / Users / Usage), Back → hub (#141) ----
            if verb == "tools":
                # Per-session Tools grid (code-only; menu.md §1.7). Render in place.
                state = None
                with contextlib.suppress(Exception):
                    state = await db.get_thread(key)
                if getattr(state, "mode", None) != "code":
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, i18n.t("settings.tools_title", lang),  # #173: rich nav-edit
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
                if mode == "code" and tool in universe:
                    base = (state.tools_enabled if state and state.tools_enabled is not None
                            else list(universe))
                    enabled = {t for t in base if t in universe}
                    enabled.discard(tool) if tool in enabled else enabled.add(tool)
                    ordered = [t for t in universe if t in enabled]
                    # None = the whole universe on (a tool added later defaults ON).
                    await db.set_tools_enabled(
                        key, None if set(ordered) == set(universe) else ordered)
                    await _rebuild_session(key)
                    state = await db.get_thread(key)
                    with contextlib.suppress(Exception):
                        await _edit_menu(msg, i18n.t("settings.tools_title", lang),  # #173: rich nav-edit
                                         _ss_tools_keyboard(state, lang))
                await cb.answer()
                return

            if verb == "users":
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer()
                return

            if verb == "usage":
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
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

            # ---- owner Admin sub-page (#178): retention + global toggles + launchers ----
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
                        await _edit_menu(  # #173: native rich nav-edit
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
                if sub == "gsl":
                    # Global default per-user session limit → arg-capture the owner's
                    # next message (a number, or off/unlimited). Handled by _run_pending.
                    pending[(msg.chat.id, thread_key(msg), uid or 0)] = "gsessionlimit"
                    with contextlib.suppress(Exception):
                        await bot.send_message(msg.chat.id, i18n.t("admin.gsl_prompt", lang),
                                               parse_mode="HTML")
                    await cb.answer()
                    return
                if sub == "cmd" and arg in ("allow", "deny", "level", "expire", "limit"):
                    # Launch an owner arg-capture command from the Admin page (#101):
                    # set up the pending capture + send the command's own prompt. The
                    # owner's next message is consumed by on_text → _run_pending → _do_*.
                    pending[(msg.chat.id, thread_key(msg), uid or 0)] = arg
                    with contextlib.suppress(Exception):
                        await bot.send_message(msg.chat.id, i18n.t(f"{arg}.prompt", lang),
                                               parse_mode="HTML")
                    await cb.answer()
                    return
                if sub == "tog" and arg in ("cs", "wp"):
                    # Global owner toggles (code-block split / working plate).
                    if arg == "cs":
                        await sessions.set_split_code_messages(
                            not bool(getattr(sessions, "split_code_messages", True)))
                    else:
                        await sessions.set_working_plate(
                            not bool(getattr(sessions, "working_plate", True)))
                    await _send_ss_admin(msg, lang)
                    await cb.answer(i18n.t("settings.saved", lang))
                    return
                # Default (sx:admin): render the Admin page.
                await _send_ss_admin(msg, lang)
                await cb.answer()
                return

            # ---- #151 access model: read-only toast + owner option-admin pages ----
            if verb == "ro":
                # A READ-ONLY row was tapped (the owner hasn't delegated it) — explain.
                await cb.answer(i18n.t("settings.ro_toast", lang), show_alert=True)
                return

            if verb == "opt" and len(parts) >= 3:
                # Owner option-admin page (Global tab): global value + base access.
                if role < ss.Role.OWNER:
                    await cb.answer(i18n.t("settings.denied", lang), show_alert=True)
                    return
                setting = ss.SETTINGS.get(parts[2])
                if setting is None:
                    await cb.answer(i18n.t("common.error", lang))
                    return
                octx = await _build_ss_ctx(key, uid, role)
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
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
                    await _edit_menu(  # #173: native rich nav-edit
                        msg,
                        i18n.t("settings.acc_title", lang, name=_setting_name(setting, lang)),
                        _ss_access_kb(setting, octx, lang))
                await cb.answer()
                return

            if verb == "accset" and len(parts) >= 4:
                # Apply a base-access change (owner) → re-render the option-admin page.
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
                        await _edit_menu(  # #173: native rich nav-edit
                            msg,
                            i18n.t("settings.opt_title", lang, name=_setting_name(setting, lang)),
                            _ss_option_admin_kb(setting, octx, lang))
                await cb.answer(i18n.t("settings.saved", lang))
                return

            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ------------------------------------------------------------ language

    def _language_keyboard(current: str) -> InlineKeyboardMarkup:
        """Inline picker listing every supported locale (✓ on the current one)."""
        rows = [
            [InlineKeyboardButton(
                text=_mark(i18n.lang_name(code), i18n.lang_name(current)),
                callback_data=f"lang:set:{code}")]
            for code in i18n.LANGUAGES
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _apply_user_menu(chat_id: int, uid: int, uname: str | None, lang: str) -> None:
        """Set this user's per-chat command menu in their chosen language + access
        level, OVERRIDING Telegram's client-language default — so /language actually
        updates the `/` menu, and a chat-level user never sees code commands. DM only."""
        is_owner = uid == settings.owner_id
        level = "code" if is_owner else (allowlist.level_of(uid, uname) or "chat")
        names = list(_COMMAND_NAMES) if level == "code" else _chat_command_names()
        if is_owner:
            names = names + _OWNER_COMMAND_NAMES
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                _build_commands(names, lang),
                scope=BotCommandScopeChat(chat_id=chat_id),
            )

    @router.message(Command("language"))
    async def cmd_language(message: Message) -> None:
        """Show the language picker, or set it directly: /language ru | en."""
        await _ensure_state(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        arg = _command_arg(message).strip().lower()
        if arg:
            base = arg.split("-", 1)[0]
            if base in i18n.LANGUAGES:
                await db.set_user_lang(uid, base)
                i18n.remember_lang(uid, base)
                # Refresh the "/" command menu in the chosen language via a per-chat
                # scope, which overrides Telegram's client-language default.
                if message.chat.type == "private":
                    uname = message.from_user.username if message.from_user else None
                    await _apply_user_menu(message.chat.id, uid, uname, base)
                await reply(message, i18n.t("lang.set", base, name=i18n.lang_name(base)))
                return
            # Unknown value: fall through to the picker.
        # No/invalid arg → the unified hub picker (USER scope; #145/#146 — one code
        # path per setting; the standalone lang: picker is retired below).
        key = await _session_key(message)
        uname = message.from_user.username if message.from_user else None
        if await _send_setting_picker(message.chat.id, key, uid, uname, lang,
                                      "language", ss.Scope.USER):
            return
        with contextlib.suppress(Exception):
            await _send_menu(  # #173: native rich menu open
                message.chat.id,
                i18n.t("lang.title", lang, name=i18n.lang_name(lang)),
                _language_keyboard(lang),
            )

    @router.callback_query(F.data.startswith("lang:"))
    async def on_language_cb(cb: CallbackQuery) -> None:
        """Apply a tap on the /language picker (set the user's interface locale)."""
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
                    await _edit_menu(  # #173: native rich (was classic edit_text)
                        cb.message,
                        i18n.t("lang.set", lang, name=i18n.lang_name(lang)),
                    )
            await cb.answer(i18n.t("common.switched", lang))
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ----------------------------------------------------------- arg capture
    # Commands needing free text (/new, /rename) can prompt and capture the
    # user's NEXT plain message as the argument, instead of forcing inline typing
    # (Telegram sends a picked command immediately). Keyed by (chat, thread, user);
    # consumed by the next plain message or cleared by /cancel.
    pending: dict[tuple, str] = {}

    def _pkey(message: Message) -> tuple:
        uid = message.from_user.id if message.from_user else 0
        return (message.chat.id, thread_key(message), uid)

    def _parse_new(arg: str) -> tuple[str, str]:
        """Parse `[chat|code] <name>` → (mode, name). No type prefix → chat."""
        parts = arg.strip().split(maxsplit=1)
        if parts and parts[0].lower() in VALID_MODES:
            return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        return "chat", arg.strip()

    async def _new_dm_session(uid: int, mode: str, name: str) -> int:
        """Create a DM session of the given (fixed) type, switch to it, return key."""
        key = await db.allocate_dm_session(
            uid, name, settings.default_model, str(settings.base_workdir), mode=mode
        )
        await db.set_dm_current(uid, key)
        return key

    async def _global_session_limit() -> int:
        """The global default per-user session limit: kv `max_sessions_default` (owner-set
        in Admin) else `settings.max_sessions_default`. 0 = unlimited."""
        raw = await db.get_kv("max_sessions_default")
        default = getattr(settings, "max_sessions_default", 10)
        try:
            return max(0, int(raw)) if raw is not None else default
        except (TypeError, ValueError):
            return default

    async def _effective_max_sessions(uid: int, uname: str | None) -> int:
        """Resolve a user's session-count cap (read-only to the user): the per-user
        override (allowlist) → the owner is uncapped by default → the GLOBAL default.
        0 = unlimited."""
        override = allowlist.max_sessions_of(uid, uname)
        if override is not None:
            return override
        if uid == settings.owner_id:
            return 0  # owner uncapped by default (#185-style; settable per-user)
        return await _global_session_limit()

    async def _session_limit_block(uid: int, uname: str | None, lang: str) -> str | None:
        """If the user is at/over their session cap, return the block message (which
        offers to delete or /clear an existing session); else None. The cap counts ALL
        of the user's sessions (chat + code)."""
        cap = await _effective_max_sessions(uid, uname)
        if cap <= 0:
            return None
        _, total = await db.browse_threads(uid, limit=1)
        if total < cap:
            return None
        return i18n.t("session.limit_reached", lang, cap=cap, total=total)

    def _default_session_name(mode: str, lang: str) -> str:
        """Localized default name for a session created without one."""
        return i18n.t(
            "session.default_name_code" if mode == "code" else "session.default_name_chat",
            lang,
        )

    def _created_text(mode: str, name: str, lang: str) -> str:
        """Confirmation shown after creating + switching to a session — leads with
        the mode glyph + tagline so the session type is unmistakable."""
        return i18n.t(
            "session.created",
            lang,
            glyph=mode_glyph(mode),
            name=markup.escape_html(name),
            tagline=mode_tagline(mode, lang=lang),
        )

    async def _do_new(message: Message, arg: str) -> None:
        # #133: every session is BORN a chat; the type is no longer fixed (/code and
        # /chat switch it later). An explicit "code" request (or /newcode) creates the
        # chat then upgrades it — only if the user has code access (#102). In the
        # (frozen) supergroup we still create a forum topic.
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
            txt = _created_text(final, name, lang)
            # On a fresh CHAT, tell code-capable users they can upgrade (#133 / req).
            if final == "chat" and can_code:
                txt += "\n" + i18n.t("session.upgrade_hint", lang)
            await reply(message, txt)
            return
        try:
            topic = await bot.create_forum_topic(chat_id=message.chat.id, name=name)
        except Exception as exc:
            await reply(
                message,
                i18n.t("topic.create_error", lang, err=markup.escape_html(str(exc))),
            )
            return
        created_name = getattr(topic, "name", name)
        await reply(
            message,
            i18n.t("topic.created", lang, name=markup.escape_html(created_name)),
        )

    async def _do_rename(message: Message, name: str, key: int | None = None) -> None:
        # DM: rename a bot-managed session (the given key, else the current one).
        # Supergroup: rename the topic.
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
        if not message.message_thread_id:
            await reply(message, i18n.t("topic.not_a_topic_rename", lang))
            return
        try:
            await bot.edit_forum_topic(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                name=name,
            )
        except Exception as exc:
            await reply(
                message,
                i18n.t("topic.rename_error", lang, err=markup.escape_html(str(exc))),
            )
            return
        await reply(
            message, i18n.t("topic.renamed", lang, name=markup.escape_html(name))
        )

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

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message) -> None:
        """Cancel a pending 'command → send the argument' prompt."""
        lang = _lang(message)
        if pending.pop(_pkey(message), None):
            await reply(message, i18n.t("common.cancelled", lang))
        else:
            await reply(message, i18n.t("common.nothing_cancel", lang))

    # --------------------------------------------------------- session browser
    # /sessions: browse + search + (DM) switch to a session. Paginated to respect
    # Telegram limits; the per-message search keyword is held in `browsers`.
    _SESSIONS_PAGE = 6
    browsers: dict[tuple, str | None] = {}  # (chat_id, msg_id) -> keyword

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
        offset: int, lang: str = "en",
    ) -> tuple[str, InlineKeyboardMarkup]:
        rows, total = await db.browse_threads(
            chat_id, keyword or None, limit=_SESSIONS_PAGE, offset=offset
        )
        head = i18n.t("sessions.head_dm" if is_dm else "sessions.head_group", lang)
        if keyword:
            head += i18n.t("sessions.head_search", lang, kw=markup.escape_html(keyword))
        head += i18n.t("sessions.head_total", lang, total=total)
        lines = [head, ""]
        kb_rows: list[list[InlineKeyboardButton]] = []
        for r in rows:
            name = _session_name(r)
            # #136: no sid shown in the list (was `sid = db.session_sid(...)`).
            reqs, toks = await _session_stats(r["thread_id"])
            mark = i18n.t("sessions.current_mark", lang) if r["thread_id"] == current_key else ""
            icon = mode_glyph(r["mode"])
            lines.append(i18n.t(
                # #211: drop {mode}/{date} — the icon conveys the mode and the date is
                # list noise. was: mode=i18n.mode_word(r["mode"], lang),
                #                  date=_fmt_date(r["created_at"]),
                "sessions.row", lang, icon=icon,
                name=markup.escape_html(name), mark=mark,
            ))
            lines.append(i18n.t("sessions.row_stats", lang, reqs=reqs, toks=toks))
            # The button is the session NAME (its sid + stats are in the text line
            # above); tapping it opens the per-session options menu (#95).
            label = f"{icon} {name[:40]}"
            if is_dm:
                # One full-width button per session = its name; tapping it opens the
                # per-session options menu (Switch · Recap · Rename · Status · ⭐ ·
                # 🗑). Favorites (⭐) sort first (browse_threads) and are marked, so
                # the list stays scannable without a control row per session (#95).
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
        nav: list[InlineKeyboardButton] = []
        if offset > 0:
            nav.append(InlineKeyboardButton(text=i18n.t("btn.prev", lang), callback_data=f"ses:pg:{max(0, offset - _SESSIONS_PAGE)}"))
        if offset + _SESSIONS_PAGE < total:
            nav.append(InlineKeyboardButton(text=i18n.t("btn.next", lang), callback_data=f"ses:pg:{offset + _SESSIONS_PAGE}"))
        if nav:
            kb_rows.append(nav)
        if is_dm:
            # New chat / New code right in the browser (next to Search/Close) so a
            # new session is one tap away while reviewing the list (#95).
            kb_rows.append(
                [
                    InlineKeyboardButton(text=i18n.t("btn.new_chat", lang), callback_data="ses:new:chat"),
                    InlineKeyboardButton(text=i18n.t("btn.new_code", lang), callback_data="ses:new:code"),
                ]
            )
        kb_rows.append(
            [
                InlineKeyboardButton(text=i18n.t("btn.search", lang), callback_data="ses:find"),
                InlineKeyboardButton(text=i18n.t("btn.close", lang), callback_data="ses:close"),
            ]
        )
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)

    async def _open_sessions(message: Message, keyword: str | None = None) -> None:
        is_dm = message.chat.type == "private"
        chat_id = message.chat.id
        current = await _session_key(message)
        text, kb = await _render_sessions(
            chat_id, is_dm, current, keyword, 0, _lang(message)
        )
        send_kwargs: dict = {}
        if message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        # #173: native rich menu open; _send_menu returns the sent Message (or None).
        sent = await _send_menu(chat_id, text, kb, **send_kwargs)
        if sent is not None:
            browsers[(chat_id, sent.message_id)] = keyword

    async def _session_card(key: int, lang: str = "en") -> str:
        st = await db.get_thread(key)
        if st is None:
            return i18n.t("common.switched", lang)
        name = st.name or ("General" if key == 0 else f"#{abs(key)}")
        reqs, toks = await _session_stats(key)
        lines = [
            i18n.t("session.switched_to", lang, glyph=mode_glyph(st.mode),
                   name=markup.escape_html(name)),
            mode_tagline(st.mode, cwd=st.cwd, lang=lang),
            i18n.t("session.card_meta", lang,
                   sid=db.session_sid(key),
                   model=MODEL_ID_TO_ALIAS.get(st.model, st.model),
                   date=_fmt_date(st.created_at), reqs=reqs, toks=toks),
        ]
        return "\n".join(lines)

    async def _owned_session(key: int, uid: int):
        """Return the ThreadState if `key` is a DM session owned by `uid`, else
        None. Ownership is chat_id OR created_by (a migrated/legacy row may carry
        only one) — used to gate every per-session options-menu action (#95)."""
        st = await db.get_thread(key)
        if st is None or (st.chat_id != uid and st.created_by != uid):
            return None
        return st

    async def _session_options(key: int, lang: str):
        """(text, keyboard) for a single session's options menu (#95): Switch ·
        Recap · Rename · Status · ⭐ favorite · 🗑 delete · Back. None if gone."""
        st = await db.get_thread(key)
        if st is None:
            return None
        name = st.name or ("General" if key == 0 else f"#{abs(key)}")
        reqs, toks = await _session_stats(key)
        text = "\n".join([
            i18n.t("sessions.options_header", lang, glyph=mode_glyph(st.mode),
                   name=markup.escape_html(name)),
            mode_tagline(st.mode, cwd=st.cwd, lang=lang),
            i18n.t("session.card_meta", lang, sid=db.session_sid(key),
                   model=MODEL_ID_TO_ALIAS.get(st.model, st.model),
                   date=_fmt_date(st.created_at), reqs=reqs, toks=toks),
        ])
        fav = bool(st.favorite)
        B = InlineKeyboardButton
        # Upgrade chat→code (only if the session OWNER has code access) / downgrade
        # code→chat (#133). The owner of a DM session is its creator.
        owner_uid = st.created_by or st.chat_id
        can_code = (owner_uid == settings.owner_id) or (allowlist.level_of(owner_uid, None) == "code")
        rows = [[B(text=i18n.t("btn.switch", lang), callback_data=f"ses:sw:{key}")]]
        # 📋 Recap is the AI one-line recap (ses:recap runs the model); the verbatim
        # last exchange is the /last command (user request 2026-06-16).
        rows += [
            [B(text=i18n.t("btn.recap", lang), callback_data=f"ses:recap:{key}"),
             B(text=i18n.t("btn.status", lang), callback_data=f"ses:status:{key}")],
            [B(text=i18n.t("btn.rename", lang), callback_data=f"ses:rename:{key}"),
             B(text=i18n.t("btn.unfavorite" if fav else "btn.favorite", lang),
               callback_data=f"ses:fav:{key}")],
        ]
        # Convert (🟩 up / 💬 down) no longer takes a full-width high row (user request
        # 2026-06-16): it moves DOWN and pairs with 📦 Export files in a code session
        # (both code-related), or with 📄 Transcript in a chat session.
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
            # Chat: no Export — pair Transcript with Convert (if the owner has code access).
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
        """Move the per-session options menu to the bottom after an action posted
        content below it: send a fresh menu, then delete the old one (#95 feedback)."""
        opts = await _session_options(key, lang)
        if opts is None:
            return
        text, kb = opts
        with contextlib.suppress(Exception):
            await _send_menu(cb.message.chat.id, text, kb)  # #173: native rich menu open
        with contextlib.suppress(Exception):
            await cb.message.delete()

    def _workdir_zip(key: int):
        """Zip the session's working directory into an in-memory archive. Returns
        (BufferedInputFile, None) or (None, error_key) — capped to keep the upload
        within Telegram's bot limit."""
        # #140: the workdir is named by the public sid, not the raw key — match it
        # (the zip FILENAME already uses the sid from #136).
        # was: root = settings.base_workdir / str(key)  — replaced for #140
        # #181: zip only the user's WORK files (state/transcript live in <sid>/state).
        root = settings.base_workdir / db.session_sid(key) / "work"
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
        # #136: name the archive by the public sid, not the raw internal id, so the
        # download doesn't leak the numbering. was: f"session-{abs(key)}-files.zip".
        return BufferedInputFile(data, filename=f"session-{db.session_sid(key)}-files.zip"), None

    @router.message(Command("sessions"))
    async def cmd_sessions(message: Message) -> None:
        """Browse / search / switch sessions (DM) or topics (supergroup)."""
        await _ensure_state(message)
        await _open_sessions(message, _command_arg(message) or None)

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
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer()
                return
            if verb in ("up", "down") and len(parts) > 2 and is_dm:
                # Upgrade / downgrade the session type (#133), then re-render the menu.
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
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer(i18n.t("mode.switched_toast", lang, mode=i18n.mode_word(new_mode, lang)))
                return
            if verb == "recap" and len(parts) > 2 and is_dm:
                # 📋 Recap → AI one-line recap of THIS session (user request
                # 2026-06-16): run the model with the recap prompt and let it stream.
                # The verbatim last prompt+reply is the /last command instead.
                key = int(parts[2])
                if await _owned_session(key, cb.from_user.id) is None:
                    await cb.answer()
                    return
                blk = await _access_block(cb.from_user.id, cb.from_user.username, lang, key)
                if blk:
                    await cb.answer(blk, show_alert=True)
                    return
                await cb.answer()  # ack before the model run streams its reply
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
                current = await db.get_dm_current(uid)
                text, kb = await _render_sessions(chat_id, is_dm, current or 0, keyword, 0, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer(i18n.t("common.created", lang))
                return
            if verb == "sw" and len(parts) > 2:
                key = int(parts[2])
                if is_dm:
                    # Only the tapper's OWN DM session (a negative key) may be
                    # switched to — a forged callback_data must not point this
                    # user at someone else's session.
                    st = await db.get_thread(key)
                    if key >= 0 or st is None or st.chat_id != cb.from_user.id:
                        await cb.answer()
                        return
                    # #102: a chat-level user may not switch INTO a code session.
                    if st.mode == "code" and allowlist.level_of(cb.from_user.id, cb.from_user.username) != "code":
                        await cb.answer(i18n.t("access.code_denied", lang), show_alert=True)
                        return
                    await db.set_dm_current(cb.from_user.id, key)
                    # Quick actions on the switch card: Recap + Transcript (#95).
                    # #136: was btn.export — it's the same ses:hist transcript as the
                    # options menu, so use the same label to avoid two names for one
                    # thing.
                    quick = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=i18n.t("btn.recap", lang), callback_data=f"ses:recap:{key}"),
                        InlineKeyboardButton(text=i18n.t("btn.transcript", lang), callback_data=f"ses:hist:{key}"),
                    ]])
                    with contextlib.suppress(Exception):
                        await _send_menu(chat_id, await _session_card(key, lang),  # #173: rich menu open
                                         quick)
                    # #136: close the now-stale options menu the Switch button came
                    # from so it doesn't linger above the switch card.
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
                # Re-render the per-session options menu so the ⭐ toggles in place.
                opts = await _session_options(key, lang)
                if opts is not None:
                    text, kb = opts
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
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
                    await _edit_menu(  # #173: native rich nav-edit
                        msg,
                        i18n.t("session.delete_confirm", lang, name=markup.escape_html(name)),
                        kb,
                    )
                await cb.answer()
                return
            if verb == "delok" and len(parts) > 2 and is_dm:
                key = int(parts[2])
                uid = cb.from_user.id
                # Capture the name BEFORE the row is dropped (for the archive meta).
                st = await db.get_thread(key)
                sname = (st.name if st else None)
                # Tear down any live subprocess/worker, then drop the row + workdir.
                with contextlib.suppress(Exception):
                    await sessions.reset(key)
                deleted = False
                with contextlib.suppress(Exception):
                    deleted = await db.delete_dm_session(uid, key)
                if deleted:
                    with contextlib.suppress(Exception):
                        # #140: workdirs are named by the public sid, not the raw key.
                        sid = db.session_sid(key)
                        # was: destroy the workdir + sbxstate outright (rmtree) —
                        #      replaced for #177. We now ARCHIVE to cold storage
                        #      instead of deleting, so nothing is lost (the transcript
                        #      lives OUTSIDE the workdir, in ~/.claude/projects/, and
                        #      was being orphaned by the old path). Retention/auto-
                        #      purge of the archives is deferred — #178.
                        # wd = settings.base_workdir / sid
                        # if wd.exists():
                        #     shutil.rmtree(wd, ignore_errors=True)
                        # sbx = settings.base_workdir / f"{sid}.sbxstate"
                        # if sbx.exists():
                        #     shutil.rmtree(sbx, ignore_errors=True)
                        archive.archive_session(
                            settings.base_workdir, sid,
                            owner_id=uid, key=key, name=sname,
                        )
                    # If the deleted session was current, switch to the most recent
                    # remaining one (or create a fresh default so there's always one).
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
                text, kb = await _render_sessions(chat_id, is_dm, current or 0, keyword, 0, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer(
                    i18n.t("common.deleted" if deleted else "session.delete_failed", lang)
                )
                return
            if verb == "pg" and len(parts) > 2:
                offset = int(parts[2])
                current = (
                    await db.get_dm_current(cb.from_user.id) if is_dm else thread_key(msg)
                )
                text, kb = await _render_sessions(chat_id, is_dm, current or 0, keyword, offset, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer()
                return
            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    # ------------------------------------------------------------------ commands

    # Help groups in display order (help_group key → header i18n key). #148.
    _HELP_GROUPS = (
        ("sessions", "help.group_sessions"),
        ("settings", "help.group_settings"),
        ("run", "help.group_run"),
        ("code", "help.group_code"),
        ("meta", "help.group_meta"),
        ("owner", "help.group_owner"),
    )

    def _help_text(message: Message) -> str:
        """Help GENERATED from the command registry (#148): intro blurb, then one
        section per help_group with each command's localized label, filtered to the
        user's access (chat users omit code/owner commands), then the footer. Keeps
        /help permanently in sync with commands.COMMANDS — no hand-maintained list."""
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
        """Create a 💬 chat session (promotable to code with /code; #133). Optional
        name: /newchat foo."""
        await _ensure_state(message)
        await _do_new(message, f"chat {_command_arg(message)}".strip())

    @router.message(Command("newcode"))
    async def cmd_newcode(message: Message) -> None:
        """Create a 🟩 code session (downgradable to chat with /chat; #133). Optional
        name: /newcode foo."""
        await _ensure_state(message)
        await _do_new(message, f"code {_command_arg(message)}".strip())

    @router.message(Command("new"))
    async def cmd_new(message: Message) -> None:
        """Create a new session — born as a 💬 chat (#133); upgrade to code with /code
        (or /newcode) when you need a terminal/files. Optional name: /new my project.
        (No more chat/code chooser — every session starts as chat and is promotable.)"""
        await _ensure_state(message)
        await _do_new(message, _command_arg(message))

    # #143: the /new chat/code chooser is DEAD — since #133 /new always creates a
    # chat (no chooser) and the /sessions browser emits ses:new:chat / ses:new:code
    # (handled by on_sessions_cb), so NOTHING emits "new:". Handler commented out
    # (kept for audit/revert); the session.new_pick i18n string is removed too.
    # @router.callback_query(F.data.startswith("new:"))
    # async def on_new_cb(cb: CallbackQuery) -> None:
    #     """Handle the /new type chooser (💬 Chat / 🟩 Code) — DM only."""
    #     try:
    #         mode = (cb.data or "new:chat").split(":", 1)[1]
    #         if mode not in VALID_MODES:
    #             mode = "chat"
    #         msg = cb.message
    #         if msg is None or msg.chat.type != "private":
    #             await cb.answer()
    #             return
    #         uid = cb.from_user.id
    #         lang = _lang(cb)
    #         if mode == "code" and allowlist.level_of(uid, cb.from_user.username) != "code":
    #             await cb.answer(i18n.t("access.code_denied", lang), show_alert=True)
    #             return
    #         name = _default_session_name(mode, lang)
    #         await _new_dm_session(uid, mode, name)
    #         with contextlib.suppress(Exception):
    #             await msg.edit_text(_created_text(mode, name, lang), parse_mode="HTML")
    #         await cb.answer(i18n.t("common.created", lang))
    #     except Exception:
    #         with contextlib.suppress(Exception):
    #             await cb.answer(i18n.t("common.error", _lang(cb)))

    async def _switch_session_mode(key: int, uid: int, uname, new_mode: str, lang: str):
        """Switch a session to new_mode (#133), carrying its conversation. Gates an
        upgrade to code by access level; the workdir files persist either way.
        Returns (reply_text, ok)."""
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
        """Upgrade the current session to a 🟩 code session (#133) — needs code access.
        Keeps the conversation; the session gets a working dir + the full toolset."""
        await _ensure_state(message)
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        text, _ = await _switch_session_mode(key, uid, uname, "code", _lang(message))
        await reply(message, text)

    @router.message(Command("chat"))
    async def cmd_chat(message: Message) -> None:
        """Downgrade the current session back to 💬 chat (#133) — keeps the conversation
        AND the workdir files (just no code tools until you /code again)."""
        await _ensure_state(message)
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        text, _ = await _switch_session_mode(key, uid, uname, "chat", _lang(message))
        await reply(message, text)

    @router.message(Command("mode"))
    async def cmd_mode(message: Message) -> None:
        """#218: TOGGLE this session's type (chat ⇄ code), carrying the conversation
        and workdir files. Upgrading to code needs code access (a guest gets the
        access-denied reply). was: only PRINTED how to switch via /code, /chat — a
        command named /mode now actually switches, reusing _switch_session_mode."""
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
            # No arg → the unified hub picker (#145/#146: one code path per setting;
            # the old standalone pm: picker is retired).
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "model"):
                return
            await reply(message, i18n.t("model.pick", lang, model=markup.escape_html(state.model)))
            return

        # Resolve a friendly alias OR an exact model id; reject anything else.
        # was: model = MODEL_ALIASES.get(arg.lower(), arg) — which set ANY string as a
        # bogus model. #215: an unknown arg now falls back to the picker (closed choice).
        arg_l = arg.lower()
        model = MODEL_ALIASES.get(arg_l) or (arg_l if arg_l in MODEL_ID_TO_ALIAS else None)
        if model is None:
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "model"):
                return
            await reply(message, i18n.t("model.pick", lang, model=markup.escape_html(state.model)))
            return

        await db.set_model(key, model)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(
            message,
            i18n.t("model.set", lang, model=markup.escape_html(model), defer=defer),
        )

    # ---- Pro commands (#23): /effort /maxturns /dirs /fork --------------------

    @router.message(Command("effort"))
    async def cmd_effort(message: Message) -> None:
        """Show/set reasoning effort: low | medium | high | xhigh | max."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        may_max = _may_max_effort(uid, uname)
        arg = _command_arg(message).lower().strip()
        if not arg:
            # No arg → the unified hub picker (#145/#146; the gated `max` level is
            # hidden by _ss_picker_keyboard for users not allowed it). The old
            # standalone pe: picker is retired.
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "effort"):
                return
            cur = state.effort or "default"
            await reply(message, i18n.t("effort.pick", lang, cur=markup.escape_html(cur)))
            return
        if arg in ("default", "reset", "none"):
            await db.set_effort(key, None)
            deferred = await _rebuild_session(key)
            defer = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("effort.reset", lang, defer=defer))
            return
        if arg not in EFFORT_LEVELS:
            await reply(message, i18n.t("effort.usage", lang))
            return
        if arg == "max" and not may_max:
            await reply(message, i18n.t("effort.max_denied", lang))
            return
        await db.set_effort(key, arg)
        deferred = await _rebuild_session(key)
        defer = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("effort.set", lang, val=arg, defer=defer))

    @router.message(Command("maxturns"))
    async def cmd_maxturns(message: Message) -> None:
        """Show/set the agentic turn cap (code mode): /maxturns N | off."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        arg = _command_arg(message).lower().strip()
        if not arg:
            # No arg → the unified hub picker (#145/#146). Code-only (menu.md §1.7);
            # in a chat session fall back to showing the value.
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
        """Branch the current session into a new one that shares history up to now
        but diverges going forward (the original is left untouched). DM only."""
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
        # Seed the branch: resume the current underlying session id, and fork on the
        # first turn so the original session is not mutated (#23).
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
        """Clear the session context and start fresh — the Claude Code /clear
        equivalent (forceful: cancels the run, drops the resume ids + transcript).
        Renamed /reset → /clear to match Claude Code (owner request); /reset kept as
        an alias."""
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

    @router.message(Command("memory"))
    async def cmd_memory(message: Message) -> None:
        """Toggle (or show) big memory for this topic: the 1M context window in
        chat plus a durable chat session that survives restarts and /stop."""
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        arg = _command_arg(message).lower()

        if not arg:
            # No arg → toggle in place (menu.md §2: "none → toggle"; #145). Was a
            # show-only text reply that forced the user to type /memory on|off.
            on = not bool(state.big_memory)
            await db.set_big_memory(key, on)
            deferred = await _rebuild_session(key)
            note = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("memory.on" if on else "memory.off", lang, note=note))
            return

        if arg not in ("on", "off"):
            await reply(message, i18n.t("memory.usage", lang))
            return

        on = arg == "on"
        if bool(state.big_memory) == on:
            await reply(message, i18n.t("memory.already", lang, state=i18n.onoff(on, lang)))
            return

        await db.set_big_memory(key, on)
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("memory.on" if on else "memory.off", lang, note=note))

    def _build_tree(root: Path, max_entries: int = 120, max_depth: int = 4) -> str:
        """A compact, read-only directory tree (depth- and entry-capped) for /files."""
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
        """Read-only tree of the current session's working directory (#100 —
        replaces /cwd + /dirs; a session's working dir is fixed)."""
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        root = Path(state.cwd)
        # #136: show the SESSION NAME, never the host path. The real cwd
        # (./workdirs/<id>) leaked the internal numbering and that the dir lives
        # above a shared parent — the user only owns "their" workspace. The path is
        # never surfaced now; only the files they create inside it.
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
            # A big tree won't fit a message (and splitting <pre> breaks tags) —
            # deliver it as a plain-text document instead. was: f"{root}\n\n{tree}"
            # (leaked the host path) — header uses the session name now.
            with contextlib.suppress(Exception):
                doc = markup.as_document(f"{state.name or ''}\n\n{tree}".strip(), "files.txt")
                await bot.send_document(chat_id=message.chat.id, document=doc)

    @router.message(Command("export"))
    async def cmd_export(message: Message) -> None:
        """Export the code session's working-directory FILES as a .zip (#104 follow-up)."""
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

    # ----------------------------------------------------- /secret (#119d)
    # Per-session user-supplied service credentials (e.g. a GitHub token). Stored in
    # <sid>/secrets.env (root-owned 0600, a sibling of the agent's workdir — NOT inside
    # it) and injected by deploy/sandbox-claude.sh as env vars into THIS session's jail
    # ONLY: never into other sessions, and the OWNER's own credentials never enter any
    # jail. A user leaking their own credential is their problem, not the owner's — the
    # #119 threat model. Values are never echoed back.
    _SECRET_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _secrets_path(key: int) -> Path:
        return settings.base_workdir / db.session_sid(key) / "secrets.env"

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
        tmp.replace(path)   # atomic swap; mode 0600 so only root (the bot) reads it

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
        # No parseable arg → list current NAMES (never values) + prompt, capturing the
        # next message as the KEY=VALUE to add (the #101 arg-capture convention).
        names = (", ".join(f"<code>{markup.escape_html(n)}</code>" for n in secrets)
                 or i18n.t("secret.none", lang))
        pending[_pkey(message)] = "secret"
        await reply(message, i18n.t("secret.help", lang, names=names))

    @router.message(Command("secret"))
    async def cmd_secret(message: Message) -> None:
        """Store a per-session service credential (e.g. a GitHub token), injected as an
        env var into THIS session's jail only (#119d). Code sessions only."""
        state = await _ensure_state(message)
        lang = _lang(message)
        if state.mode != "code":
            await reply(message, i18n.t("common.code_only", lang))
            return
        await _do_secret(message, _command_arg(message))

    @router.message(Command("sandbox"))
    async def cmd_sandbox(message: Message) -> None:
        """Owner-only: toggle the per-session bubblewrap sandbox. #180: the jail now
        covers ALL sessions (chat AND code), so there is NO mode gate — `/sandbox off`
        runs THIS session's claude WITHOUT isolation (to tell a sandbox issue apart
        from a bot bug); `/sandbox on` re-isolates. Only has effect when SANDBOX_CODE
        is enabled globally."""
        await _ensure_state(message)  # ensure the thread row exists
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        # #180: removed the code-only gate (the sandbox now applies to chat too). was:
        # if state.mode != "code":
        #     await reply(message, i18n.t("common.code_only", lang))
        #     return
        key = await _session_key(message)
        arg = _command_arg(message).lower().strip()
        if arg in ("on", "off"):
            # /sandbox on → isolate (no_sandbox=False); off → raw (no_sandbox=True).
            await db.set_no_sandbox(key, arg == "off")
            deferred = await _rebuild_session(key)
            note = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(
                message,
                i18n.t("sandbox.set_on" if arg == "on" else "sandbox.set_off", lang, note=note),
            )
            return
        # No arg → TOGGLE the effective sandbox in place (menu.md §2: "none → toggle";
        # #145). Resolve the current value via the registry (so it matches the
        # /settings hub) and flip it; no_sandbox is the inverse of "isolate".
        uid = message.from_user.id if message.from_user else None
        sctx = await _build_ss_ctx(key, uid, _role_of(uid, None))
        value, _src = ss.resolve(ss.SETTINGS["sandbox"], sctx)
        new_on = not bool(value)
        await db.set_no_sandbox(key, not new_on)
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(
            message,
            i18n.t("sandbox.set_on" if new_on else "sandbox.set_off", lang, note=note),
        )

    @router.message(Command("permissions"))
    async def cmd_permissions(message: Message) -> None:
        state = await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        # Permissions apply ONLY to code sessions. Chat carries only the read-only,
        # AUTO-approved web tools — no gated/dangerous tools (and the engine hardcodes
        # permission_mode="default" for chat) — so this setting is inert there. Say so
        # instead of storing a silent no-op (owner UX request).
        if state.mode != "code":
            await reply(message, i18n.t("perm.chat_na", lang))
            return
        arg = _command_arg(message).lower()

        if not arg:
            # No arg → the unified hub picker (#145/#146). full-access is owner-only
            # (hidden + apply-gated). The text list is the fallback.
            uid = message.from_user.id if message.from_user else None
            uname = message.from_user.username if message.from_user else None
            if await _send_setting_picker(message.chat.id, key, uid, uname, lang, "permission_mode"):
                return
            # #212: unset → new default acceptEdits. was: .get(state.permission_mode, "ask")
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

        # full-access (bypassPermissions) removes every approval gate, so it is
        # owner-only — a guest must not be able to disarm the code-mode gate.
        if arg == "full-access" and not _is_owner(message):
            await reply(message, i18n.t("perm.full_access_owner_only", lang))
            return

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
        """Owner shortcut: /auto on|off toggles code-mode auto-approval.

        on  → bypassPermissions (run every tool without asking — like a real
              Claude Code session); off → default (ask for dangerous tools).
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
            # No arg → toggle in place (menu.md §2: "none → toggle"; #145). Was a
            # show-only reply that forced typing /auto on|off.
            new_on = not is_on
            await db.set_permission_mode(key, "bypassPermissions" if new_on else "default")
            deferred = await _rebuild_session(key)
            note = i18n.t("common.defer_note", lang) if deferred else ""
            await reply(message, i18n.t("auto.on" if new_on else "auto.off", lang, note=note))
            return
        if arg not in ("on", "off"):
            await reply(message, i18n.t("auto.usage", lang))
            return

        new_mode = "bypassPermissions" if arg == "on" else "default"
        await db.set_permission_mode(key, new_mode)
        deferred = await _rebuild_session(key)
        note = i18n.t("common.defer_note", lang) if deferred else ""
        await reply(message, i18n.t("auto.on" if arg == "on" else "auto.off", lang, note=note))

    @router.message(Command("usage"))
    async def cmd_usage(message: Message) -> None:
        await _ensure_state(message)
        lang = _lang(message)
        arg = _command_arg(message).lower()

        if not arg:
            cur = getattr(sessions, "usage_mode", "footer")
            # Owner → the unified hub usage picker (#147). Non-owner → read-only text
            # (the display is account-wide; menu.md Table 7: 🟢 view · 👑 change).
            if _is_owner(message):
                with contextlib.suppress(Exception):
                    await _send_menu(  # #173: native rich menu open
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

        # The usage display is GLOBAL (the subscription windows are account-wide
        # and the pinned message is shared), so only the owner may change it — a
        # guest could otherwise flip the owner's display for everyone.
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_usage", lang))
            return

        # Prefer the SessionManager setter; fall back to the attribute so the
        # command still works even if the helper is unavailable.
        setter = getattr(sessions, "set_usage_mode", None)
        if callable(setter):
            await setter(arg)
        else:
            sessions.usage_mode = arg
        await reply(
            message,
            i18n.t("usage.set", lang, name=arg, help=i18n.t(f"usage.help.{arg}", lang)),
        )

    # ---- /codesplit (owner): each fenced code block as its OWN message --------
    # Workaround while Telegram mobile lacks a per-code-block "copy" button (desktop
    # has one): sending each block as a separate message makes long-press → Copy
    # grab the whole snippet. Owner-toggleable so it's trivial to turn OFF once the
    # mobile clients gain the copy button. Global rendering setting (#codesplit).
    def _codesplit_kb(cur: bool, lang: str) -> InlineKeyboardMarkup:
        B = InlineKeyboardButton
        return InlineKeyboardMarkup(inline_keyboard=[[
            B(text=("✓ " if cur else "") + i18n.onoff(True, lang), callback_data="csm:on"),
            B(text=("✓ " if not cur else "") + i18n.onoff(False, lang), callback_data="csm:off"),
        ]])

    @router.message(Command("codesplit"))
    async def cmd_codesplit(message: Message) -> None:
        """Owner: toggle whether each fenced code block is sent as its OWN message
        (easy mobile copy) or kept inline. Global; persisted; next-reply effect."""
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
            await _send_menu(  # #173: native rich menu open
                message.chat.id,
                i18n.t("codesplit.show", lang, state=i18n.onoff(cur, lang)),
                _codesplit_kb(cur, lang),
            )

    @router.callback_query(F.data.startswith("csm:"))
    async def on_codesplit_cb(cb: CallbackQuery) -> None:
        """Apply a /codesplit toggle tap (owner-only — it is a global setting)."""
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("codesplit.owner_only", lang))
            return
        val = (cb.data or "csm:on").split(":", 1)[1] == "on"
        await sessions.set_split_code_messages(val)
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(  # #173: native rich nav-edit
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
        """Owner: globally toggle the "Working…" + ⏹ Stop control plate (#175). OFF =
        no plate at all (A/B test whether it makes generation visibly jump). Global;
        persisted; takes effect on the next turn."""
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
            await _send_menu(  # #173: native rich menu open
                message.chat.id,
                i18n.t("workingplate.show", lang, state=i18n.onoff(cur, lang)),
                _workingplate_kb(cur, lang),
            )

    @router.callback_query(F.data.startswith("wpl:"))
    async def on_workplate_cb(cb: CallbackQuery) -> None:
        """Apply a /workingplate toggle tap (owner-only — it is a global setting)."""
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("codesplit.owner_only", lang))
            return
        val = (cb.data or "wpl:on").split(":", 1)[1] == "on"
        await sessions.set_working_plate(val)
        if cb.message is not None:
            with contextlib.suppress(Exception):
                await _edit_menu(  # #173: native rich nav-edit
                    cb.message,
                    i18n.t("workingplate.show", lang, state=i18n.onoff(val, lang)),
                    _workingplate_kb(val, lang),
                )
        with contextlib.suppress(Exception):
            await cb.answer(i18n.t("settings.saved", lang))

    # /stop command REMOVED 2026-06-15 (owner request) — the ⏹ Stop is an inline
    # BUTTON on the live control message (streamer + on_stop_cb), so a typed command
    # is redundant. Kept commented per the project convention; restore by uncommenting
    # this + re-adding "stop" to _COMMAND_NAMES.
    # @router.message(Command("stop"))
    # async def cmd_stop(message: Message) -> None:
    #     await _ensure_state(message)
    #     key = await _session_key(message)
    #     lang = _lang(message)
    #     try:
    #         stopped = await sessions.stop(key)
    #     except Exception as exc:
    #         await reply(message, i18n.t("stop.error", lang, err=markup.escape_html(str(exc))))
    #         return
    #     await reply(message, i18n.t("stop.done" if stopped else "stop.nothing", lang))

    @router.message(Command("whoami"))
    async def cmd_whoami(message: Message) -> None:
        lang = _lang(message)
        user = message.from_user
        uid = getattr(user, "id", None)
        uname = getattr(user, "username", None)
        lines = [i18n.t("whoami", lang, uid=uid, uname=uname or "-")]
        # Per-user rolling usage + any caps (#120), so a user can see their own spend.
        if uid is not None:
            try:
                bd = await db.get_user_usage_breakdown(uid)
                lines.append(i18n.t("whoami.usage", lang, day=_fmt_tokens(bd["day"]),
                                    week=_fmt_tokens(bd["week"]), total=_fmt_tokens(bd["total"])))
                rate = allowlist.rate_of(uid, uname)
                if rate.get("day") is not None or rate.get("week") is not None:
                    lines.append(i18n.t("whoami.caps", lang, caps=_fmt_caps(rate, lang)))
            except Exception:
                pass
        await reply(message, "\n".join(lines))

    def _parse_grant(arg: str) -> tuple[str, str | None, str | None, str | None]:
        """Parse ``<id|@user> [chat|code] [until DATE]`` into
        ``(target, level|None, expiry|None, error_key|None)``."""
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
            # Arg-capture (#101): no arg → prompt and capture the next message.
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
            # Arg-capture (#101): no arg → prompt and capture the next message.
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
        # Full form "<user> chat|code" → apply directly.
        if len(toks) >= 2 and toks[1].lower() in VALID_MODES:
            lvl = toks[1].lower()
            if allowlist.set_level(target, lvl):
                await reply(message, i18n.t("level.set", lang, val=markup.escape_html(target), level=lvl))
            else:
                await reply(message, i18n.t("level.not_found", lang, val=markup.escape_html(target)))
            return
        # #216: a target but no/invalid level → show a chat|code PICKER (closed choice),
        # not the level.usage error (repo convention: fixed-choice → picker). The user
        # part stays free-text (open input); only the level becomes a tap.
        # was: if len(toks) < 2 or toks[1].lower() not in VALID_MODES: reply(level.usage)
        # #220: the picker round-trips `target` through callback_data ("setlvl:<target>:<level>"),
        # which Telegram caps at 64 bytes and on_level_pick parses by ":". A ":" inside the
        # target corrupts that split and an over-long handle overflows the cap — no real
        # @username or numeric id hits either, so treat it as not-found rather than building a
        # broken button (the full-form "<user> chat|code" path above is unaffected).
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
        """Owner: set a user's access level — /level @user chat|code."""
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
        """#216: apply a chat|code choice from the /level picker (owner-only)."""
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
        """Owner: set/clear a user's access expiry — /expire @user YYYY-MM-DD|never."""
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
        # #120: /limit now sets a ROLLING-WINDOW cap (day or week), replacing the
        # #105 lifetime token grant. Syntax: /limit <id|@user> <tokens> [day|week] | off.
        #
        # was (#105 lifetime grant — top-up; replaced by rolling caps above):
        #   amt = toks[1].lower()
        #   if amt in ("off", "none", "unlimited"): tokens = None
        #   else:
        #       try:
        #           tokens = int(amt.replace("_", "").replace(",", ""))
        #           if tokens < 0: raise ValueError
        #       except ValueError: ... ; return
        #   if not allowlist.grant_tokens(target, tokens): ... ; return
        #   reply limit.unlimited / limit.set
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
        """Owner: set a user's rolling token cap — /limit @user <tokens> [day|week]|off (#120)."""
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

    async def _users_text(snap: dict, lang: str) -> list[str]:
        """The /users summary lines (owner + each entry/pending), each WITH per-user
        usage (day/week/total) — shown for everyone regardless of whether limits are
        set (owner request). The token column shows the #120 ROLLING caps (day/week)."""
        async def _usage_line(uid):
            try:
                ub = await db.get_user_units_breakdown(uid)  # #165: weighted units
                return i18n.t("users.entry_usage", lang, day=_fmt_tokens(ub["day"]),
                              week=_fmt_tokens(ub["week"]), total=_fmt_tokens(ub["total"]))
            except Exception:
                return None

        owner_id = snap.get("owner_id")
        lines = [
            i18n.t("users.header", lang),
            i18n.t("users.owner_id", lang, id=owner_id),
        ]
        ou = await _usage_line(owner_id)   # owner is uncapped but still worth seeing
        if ou:
            lines.append(ou)
        entries = snap.get("entries", {})
        pending_u = snap.get("pending", {})
        if not entries and not pending_u:
            lines.append(i18n.t("users.none_entries", lang))
        for uid, rec in entries.items():
            uname = rec.get("username")
            fname = rec.get("friendly_name")  # #171: friendly name BEFORE the @username
            _bits = []
            if fname:
                _bits.append(f"<b>{markup.escape_html(fname)}</b>")
            if uname:
                _bits.append(f"@{markup.escape_html(uname)}")
            uname_s = (" " + " ".join(_bits)) if _bits else ""
            exp = rec.get("expires_at") or i18n.t("users.never", lang)
            # was (#105 lifetime grant — replaced by #120 rolling caps):
            #   grant = rec.get("token_grant")
            #   if grant is None: quota = i18n.t("users.unlimited", lang)
            #   else: used = await db.get_user_usage_tokens(uid); quota = f"{used}/{grant}"
            quota = _fmt_caps(rec.get("rate"), lang)
            lines.append(i18n.t("users.entry", lang, id=uid, uname=uname_s,
                                level=rec.get("level", "chat"),
                                expiry=markup.escape_html(str(exp)), quota=quota))
            ul = await _usage_line(uid)
            if ul:
                lines.append(ul)
        for name, rec in pending_u.items():
            exp = rec.get("expires_at") or i18n.t("users.never", lang)
            quota = _fmt_caps(rec.get("rate"), lang)  # was: token_grant (#105 → #120)
            lines.append(i18n.t("users.pending", lang, name=markup.escape_html(name),
                                level=rec.get("level", "chat"),
                                expiry=markup.escape_html(str(exp)), quota=quota))
            # pending (un-pinned) users have no id yet → no usage to show.
        lines.append("")
        lines.append(i18n.t("users.footnote", lang))
        lines.append(i18n.t("users.tap_hint", lang))
        return lines

    def _users_keyboard(snap: dict, lang: str) -> InlineKeyboardMarkup:
        """One tappable button per user (owner first), opening their settings card
        (#120 per-user management). callback_data carries the target token: a numeric
        id for entries / the owner, or a username for an un-pinned pending user."""
        B = InlineKeyboardButton
        rows: list[list[InlineKeyboardButton]] = []
        owner_id = snap.get("owner_id")
        rows.append([B(text=i18n.t("users.btn_owner", lang), callback_data=f"usr:card:{owner_id}")])
        for uid, rec in snap.get("entries", {}).items():
            uname = rec.get("username")
            who = f"@{uname}" if uname else str(uid)
            rows.append([B(
                text=i18n.t("users.btn_entry", lang, who=who, level=rec.get("level", "chat")),
                callback_data=f"usr:card:{uid}")])
        for name, rec in snap.get("pending", {}).items():
            rows.append([B(
                text=i18n.t("users.btn_pending", lang, name=name, level=rec.get("level", "chat")),
                callback_data=f"usr:card:{name}")])
        rows.append([B(text=i18n.t("users.btn_add", lang), callback_data="usr:add"),
                     B(text=i18n.t("users.btn_stats", lang), callback_data="usr:stats")])
        rows.append([
            # #142: Back returns to the unified sx: hub (was st:nav:admin — the
            # deprecated flat hub; that was the "another menu pops up" bug).
            B(text=i18n.t("settings.back_to", lang), callback_data="sx:tab:s"),
            B(text=i18n.t("btn.close", lang), callback_data="usr:close"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _render_user_card(target: str, lang: str):
        """Build the (text, keyboard) for one user's settings card. Owner-aware: the
        owner card exposes the SELF-LIMIT toggles (memory, idle-TTL, max-effort, tool
        cap, day/week token caps — #185) but not level/expiry/access/name/remove."""
        B = InlineKeyboardButton
        d = allowlist.describe(target)
        if d is None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                B(text=i18n.t("usercard.btn_back", lang), callback_data="usr:list")]])
            return i18n.t("usercard.not_found", lang), kb
        is_owner = d["kind"] == "owner"
        base_who = f"@{d['username']}" if d.get("username") else str(d.get("id") or target)
        fname = d.get("friendly_name")  # #171: owner-assigned alias
        who = f"{fname} ({base_who})" if fname else base_who
        tid = d.get("id")
        bd = await db.get_user_usage_breakdown(tid) if tid is not None else \
            {"day": 0, "week": 0, "total": 0, "requests": 0}
        # #165: the day/week/total figures on the card are WEIGHTED USAGE UNITS (the
        # same metric the caps enforce); the request count stays from the raw breakdown.
        ub = await db.get_user_units_breakdown(tid) if tid is not None else \
            {"day": 0, "week": 0, "total": 0}
        rate = d.get("rate") or {"day": None, "week": None}

        def cap(v):
            return i18n.t("users.unlimited", lang) if v is None else _fmt_tokens(v)

        idle_raw = await db.get_user_default(tid, "idle_ttl_min") if tid is not None else None

        def _idle_lbl(v):  # #182: None → default, ≤0 → ∞, N → "{N}m"
            if v is None:
                return i18n.t("usercard.idle_default", lang)
            return "∞" if int(v) <= 0 else f"{int(v)}m"

        def _ms_lbl(v):  # session limit: None → "default", 0 → ∞, N → "{N}"
            if v is None:
                return i18n.t("usercard.sessions_default", lang)
            return "∞" if int(v) <= 0 else str(int(v))

        kind_label = (i18n.t("usercard.kind_owner", lang) if is_owner else
                      i18n.t("usercard.kind_pending", lang) if d["kind"] == "pending" else "")
        lines = [
            i18n.t("usercard.title", lang, who=markup.escape_html(who), kind=kind_label),
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
                    callback_data=f"usr:mem:{target}")
        # #182: per-user idle-TTL — shown on EVERY card, including the owner's own
        # (the owner can set it on themselves to tune/test reaper behaviour).
        idle_btn = B(text=i18n.t("usercard.btn_idle", lang, val=_idle_lbl(idle_raw)),
                     callback_data=f"usr:idle:{target}")
        ses_btn = B(text=i18n.t("usercard.btn_sessions", lang, val=_ms_lbl(d.get("max_sessions"))),
                    callback_data=f"usr:max:{target}")
        if is_owner:
            # #185: the owner can self-impose the per-user limits (to TEST them). Show
            # the same toggles as a guest EXCEPT level/expiry/access/name/remove (the
            # owner is always code, never expires, always full access, can't self-remove).
            # was: rows.append([mem_btn, idle_btn])
            rows.append([mem_btn,
                         B(text=i18n.t("usercard.btn_maxeffort", lang, state=i18n.onoff(d.get("allow_max_effort"), lang)),
                           callback_data=f"usr:eff:{target}")])
            rows.append([B(text=i18n.t("usercard.btn_tools", lang, val=_fmt_cap(d.get("tool_cap"), lang)),
                           callback_data=f"usr:tools:{target}"),
                         idle_btn])
            rows.append([B(text=i18n.t("usercard.btn_day", lang), callback_data=f"usr:rday:{target}"),
                         B(text=i18n.t("usercard.btn_week", lang), callback_data=f"usr:rweek:{target}"),
                         ses_btn])
            if rate.get("day") is not None or rate.get("week") is not None:
                rows.append([B(text=i18n.t("usercard.btn_clear_limits", lang), callback_data=f"usr:rclr:{target}")])
        else:
            nxt = "code" if d.get("level") == "chat" else "chat"
            rows.append([B(text=i18n.t("usercard.btn_level", lang, level=d.get("level", "chat"), next=nxt),
                           callback_data=f"usr:lvl:{target}"),
                         ses_btn])
            rows.append([mem_btn,
                         B(text=i18n.t("usercard.btn_maxeffort", lang, state=i18n.onoff(d.get("allow_max_effort"), lang)),
                           callback_data=f"usr:eff:{target}")])
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
        """(text, keyboard) for the per-user TOOL CAP sub-page (#131): toggle which
        tools this user may use at all. cap=None = every tool allowed."""
        B = InlineKeyboardButton
        d = allowlist.describe(target)
        # #185: the owner CAN open its own tool-cap sub-page now (self-impose for testing).
        # was: if d is None or d["kind"] == "owner": return await _render_user_card(...)
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
        """(text, keyboard) for the per-user ACCESS-exceptions sub-page (#151, menu.md
        §3.4/§4): one row per option showing this user's effective access — their
        EXCEPTION if set, else the owner's base for that option. Tapping opens a
        per-option picker (Base / Delegated / Read-only / Hidden)."""
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
        """Per-option access picker on a user card: Base (clear) / Delegated /
        Read-only / Hidden, then Back → the user's access sub-page (#151)."""
        B = InlineKeyboardButton
        opts = [("base", i18n.t("usercard.access_base_opt", lang)),
                ("delegated", _access_label(ss.Access.DELEGATED, lang)),
                ("readonly", _access_label(ss.Access.READONLY, lang)),
                ("hidden", _access_label(ss.Access.HIDDEN, lang))]
        btns = [B(text=lbl, callback_data=f"usr:accset:{target}:{skey}:{lv}") for lv, lbl in opts]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        rows.append([B(text=i18n.t("btn.back", lang), callback_data=f"usr:acc:{target}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.message(Command("users"))
    async def cmd_users(message: Message) -> None:
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        snap = allowlist.snapshot()
        await _send_menu(  # #173: native rich menu open
            message.chat.id, "\n".join(await _users_text(snap, lang)),
            _users_keyboard(snap, lang),
        )

    @router.callback_query(F.data.startswith("usr:"))
    async def on_user_cb(cb: CallbackQuery) -> None:
        """Per-user management card taps (#120). Owner-only: a guest must never
        manage access. Mutations re-render the card in place; free-text values
        (expiry / day / week caps) go through arg-capture (_apply_user_value)."""
        lang = _lang(cb)
        if not (cb.from_user and cb.from_user.id == settings.owner_id):
            await cb.answer(i18n.t("common.owner_only_access", lang))
            return
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
                # ➕ Add user — arg-capture (reuses /allow's prompt + _do_allow path).
                pending[(msg.chat.id, thread_key(msg), cb.from_user.id)] = "allow"
                with contextlib.suppress(Exception):
                    await bot.send_message(msg.chat.id, i18n.t("allow.prompt", lang), parse_mode="HTML")
                await cb.answer()
                return
            if verb == "list":
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer()
                return
            if verb == "stats":
                # #172: the 📊 button on the /users page → the per-user stats table,
                # so /userstats is reachable from the menu (not just by typing it).
                send_kwargs: dict = {}
                if msg.chat.type != "private" and msg.message_thread_id:
                    send_kwargs["message_thread_id"] = msg.message_thread_id
                await _send_userstats(msg.chat.id, send_kwargs, lang)
                await cb.answer()
                return
            if verb in ("exp", "rday", "rweek", "name", "idle", "max"):
                # Free-text value → arg-capture the owner's next message.
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
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer()
                return
            if verb == "tcap":
                # target carries "<target>:<toolname>" (split(":",2) kept it whole).
                tgt, _, tool = target.partition(":")
                d = allowlist.describe(tgt)
                # #185: allow the owner to toggle its OWN tool cap (was `d["kind"] != "owner"`).
                if d and tool in ALL_TOOLS:
                    cap = d.get("tool_cap")
                    allowed = set(cap) if cap is not None else set(ALL_TOOLS)
                    allowed.discard(tool) if tool in allowed else allowed.add(tool)
                    ordered = [t for t in ALL_TOOLS if t in allowed]
                    # Store None when ALL tools are allowed, so a tool added later
                    # stays allowed by default; otherwise the explicit allowed list.
                    allowlist.set_tool_cap(tgt, None if set(ordered) == set(ALL_TOOLS) else ordered)
                text, kb = await _render_user_tools(tgt, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer()
                return
            if verb == "acc":
                # Per-user ACCESS-exceptions sub-page (#151, menu.md §3.4).
                text, kb = await _render_user_access(target, lang)
                with contextlib.suppress(Exception):
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
                await cb.answer()
                return
            if verb == "accopt":
                # Open the per-option access picker. target = "<target>:<option>".
                tgt, _, skey = target.partition(":")
                if skey not in ss.SETTINGS:
                    await cb.answer()
                    return
                setting = ss.SETTINGS[skey]
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
                        msg,
                        i18n.t("usercard.access_opt_title", lang,
                               name=_setting_name(setting, lang)),
                        _user_access_picker_kb(tgt, skey, lang))
                await cb.answer()
                return
            if verb == "accset":
                # Apply a per-user access exception. target = "<target>:<option>:<level>".
                bits = target.split(":")
                if len(bits) >= 3:
                    tgt, skey, level = bits[0], bits[1], bits[2]
                    if skey in ss.SETTINGS:
                        allowlist.set_access_exception(
                            tgt, skey, None if level == "base" else level)
                    text, kb = await _render_user_access(tgt, lang)
                    await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
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
                    await _edit_menu(  # #173: native rich nav-edit
                        msg, i18n.t("usercard.confirm_remove", lang,
                                    who=markup.escape_html(target)),
                        kb)
                await cb.answer()
                return
            if verb == "delok":
                allowlist.remove(target)
                snap = allowlist.snapshot()
                with contextlib.suppress(Exception):
                    await _edit_menu(  # #173: native rich nav-edit
                        msg, "\n".join(await _users_text(snap, lang)),
                        _users_keyboard(snap, lang))
                await cb.answer(i18n.t("common.deleted", lang))
                return
            # In-place toggles (re-render the card afterwards).
            if verb == "lvl":
                d = allowlist.describe(target)
                if d:
                    allowlist.set_level(target, "code" if d.get("level") == "chat" else "chat")
            elif verb == "mem":
                d = allowlist.describe(target)
                if d:
                    allowlist.set_global_memory(target, not d.get("global_memory"))
            elif verb == "eff":
                d = allowlist.describe(target)
                if d:
                    allowlist.set_allow_max_effort(target, not d.get("allow_max_effort"))
            elif verb == "rclr":
                allowlist.set_rate(target, day=None, week=None)
            text, kb = await _render_user_card(target, lang)
            with contextlib.suppress(Exception):
                await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
            await cb.answer()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", lang))

    async def _apply_user_value(message: Message, action: str, text: str) -> None:
        """Apply an arg-captured user-card value (expiry / day cap / week cap /
        friendly name), then re-post the card. action is 'usrexp:<t>' / 'usrrday:<t>'
        / 'usrrweek:<t>' / 'usrname:<t>' (#171)."""
        lang = _lang(message)
        if not _is_owner(message):
            return
        kind, _, target = action.partition(":")
        raw = text.strip()
        if kind == "usrname":
            # '-' / off / none / clear wipes the alias; otherwise set it.
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
            # '0' is NOT a clear here — it sets a 0-token deny-all cap, consistent
            # with `/limit @user 0 day` (#120 audit). Clear with off/none/unlimited.
            if raw.lower() in ("off", "none", "unlimited"):
                allowlist.set_rate(target, **{window: None})
            else:
                n = _parse_token_amount(raw)
                if n is None:
                    await reply(message, i18n.t("limit.bad", lang))
                    return
                allowlist.set_rate(target, **{window: n})
        elif kind == "usridle":
            # #182: per-user idle-TTL (minutes). off/none/inf/∞/never/0 → 0 (never
            # reap); default/clear → unset (fall back to the server default); else a
            # positive integer of minutes. Stored in the per-uid KV keyed by uid, so
            # it works for ANY target including the owner (no allowlist entry needed).
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
            # Per-user session-count cap. default/clear/- → inherit the global default;
            # off/none/unlimited/0 → 0 (unlimited); else a positive integer.
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
        await _send_menu(message.chat.id, card_text, kb)  # #173: native rich user card

    async def _set_global_session_limit(message: Message, text: str) -> None:
        """Owner sets the GLOBAL default per-user session limit (kv `max_sessions_default`;
        applies to users without a per-user override). off/none/unlimited/0 → unlimited."""
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

        # #135: refresh the account usage so /status shows the LIVE per-window % (not
        # a stale snapshot from the last turn / poll). Best-effort.
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

        # #212: unset → new default acceptEdits. was: .get(state.permission_mode, "ask")
        perm_name = PERM_MODE_TO_NAME.get(state.permission_mode or "acceptEdits", "auto-edits")
        usage_mode = getattr(sessions, "usage_mode", "footer")
        # Streaming setting RETIRED (native streaming always on); see /stream note.
        # stream_on = bool(st.get("stream", True))

        lang = _lang(message)
        sess_name = state.name or ("General" if key == 0 else f"#{abs(key)}")
        lines: list[str] = [
            "<h3>" + i18n.t("status.header", lang, glyph=mode_glyph(str(mode)),
                            name=markup.escape_html(sess_name),
                            mode=i18n.mode_word(str(mode), lang),
                            sid=db.session_sid(key)) + "</h3>",
        ]
        lines.append(i18n.t("status.model", lang, model=markup.escape_html(str(model))))
        if mode == "code":
            lines.append(i18n.t("status.directory", lang, cwd=markup.escape_html(str(cwd))))
            lines.append(i18n.t("status.permissions", lang, perm=markup.escape_html(perm_name)))
        lines.append(i18n.t("status.usage_display", lang, usage=markup.escape_html(str(usage_mode))))
        # Streaming row RETIRED (native streaming always on); restore with /stream.
        # lines.append(i18n.t("status.streaming", lang, state=i18n.onoff(stream_on, lang)))
        # #170: session flags as a NATIVE checklist (the checkbox is the on/off).
        _chk = lambda on: " checked" if on else ""  # noqa: E731
        lines.append(
            "<ul>"
            f'<li><input type="checkbox"{_chk(bool(state.big_memory))}> '
            f'{markup.escape_html(i18n.t("status.chk_bigmem", lang))}</li>'
            f'<li><input type="checkbox"{_chk(busy)}> '
            f'{markup.escape_html(i18n.t("status.chk_busy", lang, queued=queued))}</li>'
            "</ul>"
        )
        lines.append(i18n.t("status.cache", lang, secs=int(cache_left)))

        # #172: subscription usage windows as a native LIST — a bold header then one
        # <li> per window (5h, 7d, 7d Opus, 7d Sonnet, …) so it reads cleanly instead
        # of a run-on line. Falls back to the latest per-thread snapshot.
        rbt = getattr(sessions, "rate_by_type", {}) or {}
        win_items = []
        with contextlib.suppress(Exception):
            for _wk in usage.WINDOW_ORDER:
                _info = rbt.get(_wk)
                if _info is not None:
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

        # Small utilization trend per window (#15), when we have numeric history.
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

        # #172: per-session usage TOTALS as a native list.
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

        # #170: render /status as a native rich message (heading + checklist).
        await reply_rich_html(message, "\n".join(lines))

    @router.message(Command("context"))
    async def cmd_context(message: Message) -> None:
        """Show the live session's context-window token usage (best effort)."""
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

        # Format defensively: the SDK returns a ContextUsageResponse, which is a
        # TypedDict (dict subclass) with keys totalTokens / maxTokens /
        # percentage. We also tolerate a legacy attribute-style object or None.
        # _cu() reads the first present key/attr from either shape; we prefer the
        # SDK's own percentage when given, else derive it from used/total. Never
        # raise — fall back to a compact string for a genuinely unknown shape.
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
        """Show the caller's OWN rolling usage limits (#164). For the owner this
        instead shows the REAL account/subscription usage (the global windows) —
        a delegated user never sees the owner's account-wide numbers."""
        await _ensure_state(message)
        lang = _lang(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None

        if _is_owner(message):
            # Owner → the real account (subscription) usage, refreshed live.
            with contextlib.suppress(Exception):
                await sessions.refresh_account_usage()
            body = usage.pinned_text(getattr(sessions, "rate_by_type", {}) or {}, lang)
            if body:
                await reply(message, i18n.t("limits.account_header", lang) + "\n" + body)
            else:
                await reply(message, i18n.t("limits.account_empty", lang))
            return

        # Delegated user → their own trailing-24h / trailing-7d use vs cap. #165: the
        # day/week figures and the caps are WEIGHTED USAGE UNITS (cost-aware), while the
        # request count still comes from the raw breakdown.
        bd = await db.get_user_usage_breakdown(uid)      # for the request count
        ub = await db.get_user_units_breakdown(uid)      # weighted units (#165)
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
            i18n.t("limits.units_note", lang),
        ]
        await reply(message, "\n".join(lines))

    async def _send_userstats(chat_id: int, send_kwargs: dict, lang: str) -> None:
        """#164: build + send the per-user usage dashboard as a NATIVE table (one row
        per user: trailing-day / week / lifetime tokens, requests, last-seen). Falls
        back to a monospace grid if sendRichMessage fails. Shared by /userstats and the
        📊 button on the /users page (#172)."""
        rows = await db.get_all_users_usage()
        if not rows:
            with contextlib.suppress(Exception):
                await bot.send_message(chat_id, i18n.t("userstats.empty", lang),
                                       parse_mode="HTML", **send_kwargs)
            return
        # uid → friendly-name / @username label from the allowlist snapshot.
        labels: dict[int, str] = {}
        with contextlib.suppress(Exception):
            for sid, rec in (allowlist.snapshot().get("entries") or {}).items():
                try:
                    luid = int(sid)
                except (TypeError, ValueError):
                    continue
                uname = rec.get("username")
                fname = rec.get("friendly_name")  # #171: prefer the owner's alias
                labels[luid] = fname or (f"@{uname}" if uname else str(luid))
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

        header = [
            i18n.t("userstats.col_user", lang), i18n.t("userstats.col_day", lang),
            i18n.t("userstats.col_week", lang), i18n.t("userstats.col_total", lang),
            i18n.t("userstats.col_req", lang), i18n.t("userstats.col_last", lang),
        ]
        trows = [header]
        for r in rows:
            uid = r["uid"]
            label = labels.get(uid, str(uid))
            if uid == settings.owner_id:
                label = f"👑 {label}"
            trows.append([
                label, _fmt_tokens(r["day"]), _fmt_tokens(r["week"]),
                _fmt_tokens(r["total"]), str(r["requests"]), _ago(r["last_ts"]),
            ])
        aligns = ["left", "right", "right", "right", "right", "right"]
        title = f"<b>👥 {markup.escape_html(i18n.t('userstats.title', lang))}</b>"
        html = title + markup.table_to_rich_html(trows, aligns)
        try:
            await bot(SendRichMessage(
                chat_id=chat_id, rich_message={"html": html}, **send_kwargs))
        except Exception:
            esc = [[markup.escape_html(c) for c in row] for row in trows]
            with contextlib.suppress(Exception):
                await bot.send_message(chat_id, markup._render_table_pre(esc),
                                       parse_mode="HTML", **send_kwargs)

    @router.message(Command("userstats"))
    async def cmd_userstats(message: Message) -> None:
        """Owner-only per-user usage dashboard (native table, #164)."""
        lang = _lang(message)
        if not _is_owner(message):
            await reply(message, i18n.t("common.owner_only_access", lang))
            return
        send_kwargs: dict = {}
        if message.chat.type != "private" and message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        await _send_userstats(message.chat.id, send_kwargs, lang)

    @router.message(Command("test"))
    async def cmd_test(message: Message) -> None:
        """#172: owner-only self-test — SIMULATE a streamed generation (3 paragraphs +
        a 5×5 table + an asm snippet) so the live rich-draft formatting can be eyeballed
        (it should format as it streams, not snap to rich at the end)."""
        if not _is_owner(message):
            return
        await sessions.stream_demo(message.chat.id)

    async def _recap_messages(key: int, lang: str) -> list[str]:
        """Build a session's last exchange as ready-to-send HTML message(s).

        Claude's reply is RENDERED (md_to_html) — escape_html would leak literal
        headers / bold / code fences. The user's prompt is shown verbatim
        (escaped). A long, code-heavy reply is split into size-safe rendered chunks
        (never splitting already-rendered HTML across a tag). The transcript table
        (#47) is separate from the model's SDK-resumed memory, so an empty log with
        a live session id says so accurately rather than "no conversation".
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
        """Show the last exchange VERBATIM (your last prompt + Claude's last reply).
        Was /recap before 2026-06-16; /recap now generates an AI one-line recap."""
        await _ensure_state(message)
        key = await _session_key(message)
        lang = _lang(message)
        for chunk in await _recap_messages(key, lang):
            await reply(message, chunk)

    @router.message(Command("recap"))
    async def cmd_recap(message: Message) -> None:
        """Generate a one-line AI recap of the current session — the model summarizes
        the conversation so far (like Claude Code's /recap). For the verbatim last
        prompt+reply, use /last (user request 2026-06-16). Runs a model turn, so it
        goes through the normal access/quota gate + streaming via _submit."""
        await _ensure_state(message)
        lang = _lang(message)
        await _submit(message, i18n.t("recap.prompt", lang))

    async def _history_doc(key: int, lang: str):
        """Build a session's transcript as a Markdown document. Returns
        (document, None) on success, or (None, note) when there's nothing to
        export (or building failed) so the caller can show the note. Also used by
        the /sessions Export quick-action (#95)."""
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

    # --- /stream toggle RETIRED (owner, 2026-06-15) -------------------------- #
    # DM uses native Telegram streaming (sendMessageDraft), which is always on, so
    # the per-session live-vs-single-message toggle is no longer needed. The whole
    # handler is COMMENTED OUT (not deleted) so streaming/speed control can be
    # restored by uncommenting this block + re-adding a /settings row + a stream apply
    # branch (the old _settings_apply "stream" branch was removed in #214). The
    # underlying plumbing (sessions.set_stream, the
    # stream_enabled column, rec.stream_enabled) is intentionally kept intact.
    # @router.message(Command("stream"))
    # async def cmd_stream(message: Message) -> None:
    #     """Toggle (or show) whether replies stream live vs arrive as one message."""
    #     await _ensure_state(message)
    #     key = await _session_key(message)
    #     lang = _lang(message)
    #     arg = _command_arg(message).lower()
    #
    #     if not arg:
    #         try:
    #             st = sessions.status(key) or {}
    #         except Exception:
    #             st = {}
    #         current = i18n.onoff(bool(st.get("stream", True)), lang)
    #         await reply(message, i18n.t("stream.show", lang, current=current))
    #         return
    #
    #     if arg not in ("on", "off"):
    #         await reply(message, i18n.t("stream.usage", lang))
    #         return
    #
    #     enabled = arg == "on"
    #     try:
    #         await sessions.set_stream(key, enabled)
    #     except Exception as exc:
    #         await reply(
    #             message,
    #             i18n.t("stream.change_error", lang, err=markup.escape_html(str(exc))),
    #         )
    #         return
    #     await reply(message, i18n.t("stream.set", lang, state=i18n.onoff(enabled, lang)))

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
        """Close the current forum topic (only valid inside a real topic)."""
        await _ensure_state(message)
        lang = _lang(message)
        if not message.message_thread_id:
            await reply(message, i18n.t("topic.not_a_topic_close", lang))
            return
        try:
            await bot.close_forum_topic(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
            )
        except Exception as exc:
            await reply(
                message,
                i18n.t("topic.close_error", lang, err=markup.escape_html(str(exc))),
            )
            return
        await reply(message, i18n.t("topic.closed", lang))

    async def _render_queue(key: int, lang: str = "en") -> tuple[str, InlineKeyboardMarkup | None]:
        """Build the /queue view: each pending prompt with a ✖ cancel button."""
        try:
            items = sessions.queue_items(key)
        except Exception:
            items = []
        if not items:
            return i18n.t("queue.empty", lang), None
        lines = [i18n.t("queue.header", lang, n=len(items))]
        kb_rows: list[list[InlineKeyboardButton]] = []
        for i, it in enumerate(items, start=1):
            lines.append(f"{i}. <code>{markup.escape_html(str(it['text']))}</code>")
            kb_rows.append([InlineKeyboardButton(
                text=i18n.t("queue.cancel_btn", lang, i=i), callback_data=f"qx:{key}:{it['id']}")])
        kb_rows.append([
            InlineKeyboardButton(text=i18n.t("btn.clear_all", lang), callback_data=f"qx:{key}:all"),
            InlineKeyboardButton(text=i18n.t("btn.close", lang), callback_data="qx:close"),
        ])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)

    @router.message(Command("queue"))
    async def cmd_queue(message: Message) -> None:
        """Show the prompts waiting to run next, each with a cancel button."""
        await _ensure_state(message)
        key = await _session_key(message)
        text, kb = await _render_queue(key, _lang(message))
        send_kwargs: dict = {}
        if message.message_thread_id:
            send_kwargs["message_thread_id"] = message.message_thread_id
        # #173: native rich menu open
        await _send_menu(message.chat.id, text, kb, **send_kwargs)

    @router.callback_query(F.data.startswith("qx:"))
    async def on_queue_cb(cb: CallbackQuery) -> None:
        """Handle /queue cancel taps (cancel one by id, clear all, or close)."""
        try:
            parts = (cb.data or "").split(":")
            msg = cb.message
            if msg is None:
                await cb.answer()
                return
            lang = _lang(cb)
            if len(parts) >= 2 and parts[1] == "close":
                with contextlib.suppress(Exception):
                    await msg.delete()
                await cb.answer()
                return
            key = int(parts[1])
            # Only the tapper's OWN DM session (a negative key) may be touched —
            # never let a forged callback_data clear/cancel another user's queue.
            st = await db.get_thread(key)
            if key >= 0 or st is None or st.chat_id != cb.from_user.id:
                await cb.answer()
                return
            target = parts[2] if len(parts) > 2 else ""
            if target == "all":
                n = await sessions.clear_queue(key)
                await cb.answer(i18n.t("queue.cleared_toast", lang, n=n))
            else:
                removed = await sessions.cancel_queued(key, int(target))
                await cb.answer(i18n.t("queue.cancelled_toast" if removed else "queue.already_running", lang))
            text, kb = await _render_queue(key, lang)
            with contextlib.suppress(Exception):
                await _edit_menu(msg, text, kb)  # #173: native rich nav-edit
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    @router.callback_query(F.data.startswith("stop:"))
    async def on_stop_cb(cb: CallbackQuery) -> None:
        """Inline ⏹ Stop button (on the per-turn control message) → graceful stop."""
        try:
            lang = _lang(cb)
            parts = (cb.data or "").split(":")
            tid = int(parts[1]) if len(parts) > 1 else 0
            # Only the tapper's OWN DM session (a negative key) may be stopped —
            # a forged callback_data must not interrupt another user's turn.
            st = await db.get_thread(tid)
            if tid >= 0 or st is None or st.chat_id != cb.from_user.id:
                await cb.answer()
                return
            stopped = await sessions.stop(tid)
            await cb.answer(i18n.t("stopbtn.stopping" if stopped else "stopbtn.nothing", lang))
            if cb.message is not None:
                if stopped:
                    # Instant feedback: grey out the button; the streamer removes the
                    # whole control message once the interrupted turn finishes.
                    with contextlib.suppress(Exception):
                        await cb.message.edit_reply_markup(reply_markup=None)
                else:
                    # Nothing to stop — typically an ORPHANED control message left
                    # over after a bot restart (the new process has no record of that
                    # turn, so its Stop button is dead). Delete the stale message so
                    # the button clears instead of lingering forever.
                    with contextlib.suppress(Exception):
                        await cb.message.delete()
        except Exception:
            with contextlib.suppress(Exception):
                await cb.answer(i18n.t("common.error", _lang(cb)))

    @router.message(Command("clearqueue"))
    async def cmd_clearqueue(message: Message) -> None:
        """Drop the queued prompts without stopping the current run."""
        await _ensure_state(message)
        key = await _session_key(message)
        try:
            n = await sessions.clear_queue(key)
        except Exception as exc:
            await reply(
                message,
                i18n.t("queue.clear_error", _lang(message), err=markup.escape_html(str(exc))),
            )
            return
        await reply(message, i18n.t("queue.cleared", _lang(message), n=int(n or 0)))

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

    # ----------------------------------------------------------- plain text

    async def _access_block(uid: int | None, uname: str | None, lang: str, key: int) -> str | None:
        """Pre-turn access gate (#102/#105). Returns an i18n denial string if the
        user may NOT run a turn right now — a chat-level user in a code session, or
        a user over their token quota — else None. The owner is exempt (level_of →
        "code", token_grant_of → None, so neither check fires). Takes the acting
        identity directly so callback handlers (e.g. the session-menu AI recap
        button) can gate a turn too, not only message handlers."""
        uid = uid or 0
        st = await db.get_thread(key)
        if st is not None and st.mode == "code" and allowlist.level_of(uid, uname) != "code":
            return i18n.t("access.code_denied", lang)
        # Effort gate enforced PER-TURN (#123 audit): the max-effort permission is
        # checked at selection time, but if the owner later revokes it a stored
        # effort=max would keep burning the shared subscription. Downgrade it here so
        # revocation takes effect on the next turn (handle_text then rebuilds the
        # session) — mirrors the run-time code-level gate above. Owner is exempt.
        if st is not None and st.effort == "max" and not _may_max_effort(uid, uname):
            await db.set_effort(key, "xhigh")
        # Rolling-window rate limits (#120 → #165): deny when the user's trailing-24h or
        # trailing-7d WEIGHTED USAGE UNITS reach their cap. Windows are computed from
        # usage timestamps, so they free up on their own (no reset job). #165: the cap
        # now counts cost-weighted units (model weight + cache + output) instead of raw
        # input+output, so a big warm context no longer reads as near-zero spend; caps
        # are therefore interpreted in units (≈ Sonnet-input-token-equivalents). The
        # legacy lifetime token_grant (#105) is not enforced — superseded by these.
        rate = allowlist.rate_of(uid, uname)
        now = time.time()
        day_cap = rate.get("day")
        if day_cap is not None:
            used = await db.get_user_usage_units(uid, since=now - 86400)
            if used >= day_cap:
                return i18n.t("access.rate_day_exceeded", lang,
                              used=_fmt_tokens(used), cap=_fmt_tokens(day_cap))
        week_cap = rate.get("week")
        if week_cap is not None:
            used = await db.get_user_usage_units(uid, since=now - 7 * 86400)
            if used >= week_cap:
                return i18n.t("access.rate_week_exceeded", lang,
                              used=_fmt_tokens(used), cap=_fmt_tokens(week_cap))
        return None

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        """Route a plain text message into the thread's Claude session."""
        # Ignore the bot's own messages defensively (normally not delivered).
        if message.from_user is not None and message.from_user.is_bot:
            return
        text = (message.text or "").strip()
        if not text:
            return
        # If a command is awaiting its argument (e.g. /new just asked for a name),
        # consume this message as that argument instead of routing it to the model.
        action = pending.pop(_pkey(message), None)
        if action:
            await _run_pending(action, message, text)
            return
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        block = await _access_block(uid, uname, _lang(message), key)
        if block:
            await reply(message, block)
            return
        try:
            await sessions.handle_text(message.chat.id, key, text)
        except Exception as exc:
            await reply(
                message,
                i18n.t("text.process_error", _lang(message), err=markup.escape_html(str(exc))),
            )

    # -------------------------------------------------------- attachments

    async def _submit(message: Message, text: str, attachments=None) -> None:
        """Route a turn (text + optional content blocks) into the thread session."""
        key = await _session_key(message)
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        block = await _access_block(uid, uname, _lang(message), key)
        if block:
            await reply(message, block)
            return
        try:
            await sessions.handle_text(
                message.chat.id, key, text, attachments=attachments
            )
        except Exception as exc:
            await reply(
                message,
                i18n.t("attach.process_error", _lang(message), err=markup.escape_html(str(exc))),
            )

    async def _download(downloadable, limit: int, file_size: int | None, lang: str = "en"):
        """Download a Telegram file to bytes. Returns (bytes, None) on success or
        (None, user_message) when it is too large or cannot be read."""
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
        """A Telegram photo → image content block (Telegram photos are JPEG)."""
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        photo = message.photo[-1]  # the largest available size
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
        await _submit(message, caption or i18n.t("attach.default_image_prompt", lang), [block])

    @router.message(F.document)
    async def on_document(message: Message) -> None:
        """A file attachment → image block, PDF document block, or inlined text.

        Dispatch by mime/extension: images and PDFs go to the model as content
        blocks; a UTF-8-decodable text/code file is inlined into the prompt;
        anything else is rejected with a hint. Works in chat and code mode.
        """
        if message.from_user is not None and message.from_user.is_bot:
            return
        lang = _lang(message)
        doc = message.document
        mime = (getattr(doc, "mime_type", "") or "").lower()
        fname = getattr(doc, "file_name", None) or "file"
        size = getattr(doc, "file_size", None)
        caption = (message.caption or "").strip()

        # Image sent as a file (uncompressed).
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
            await _submit(message, caption or i18n.t("attach.default_image_prompt", lang), [block])
            return

        # PDF → document block (native PDF understanding: text + page images).
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
            await _submit(message, caption or i18n.t("attach.default_doc_prompt", lang), [block])
            return

        # Text/code file → inline the decoded content into the prompt.
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
        header = caption or i18n.t("attach.default_doc_prompt", lang)
        await _submit(message, f"{header}\n\n--- {fname} ---\n{content}{note}")

    # ------------------------------------------------- permission callbacks

    @router.callback_query(F.data.startswith("perm:"))
    async def on_perm_callback(callback_query: CallbackQuery) -> None:
        """Forward an inline-button decision to the PermissionGate.

        Authorizing a dangerous tool is an OWNER-ONLY action. The allowlist gates
        who may talk to the bot, but only the owner may approve Bash/Write/Edit in
        code mode — otherwise a guest could green-light arbitrary host commands.
        A non-owner tap is acknowledged and ignored; the prompt stays open for the
        owner to decide.
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
            # Never let a callback failure bubble up; acknowledge politely.
            try:
                await callback_query.answer(i18n.t("permgate.processing_error", _lang(callback_query)))
            except Exception:
                pass

    return router


# --------------------------------------------------------------- settings menu
# An inline-button menu (/settings) so settings are changed by tapping instead of
# typing a "kilometer of commands". callback_data is compact ("st:<verb>:<args>")
# to stay under Telegram's 64-byte limit.


def _mark(name: str, current: str) -> str:
    """Button label with a ✓ when this option is the current value."""
    return f"✓ {name}" if name == current else name


# --------------------------------------------------------------- #138 PART 2
# Generic, REGISTRY-DRIVEN /settings UI (settings_schema). Three scope tabs —
# "This session" / "My defaults" / "Global" — gated by the role matrix: non-owners
# never see the Global tab nor the owner-only rows (sandbox, global model). Each
# visible Setting renders as one row showing its RESOLVED value + a badge of WHICH
# scope supplies it, with an inline control (picker for a fixed choice, on/off
# toggle for a bool). callback_data stays compact:
#   sx:hub            — the tabbed hub (defaults to the session tab)
#   sx:tab:<sc>       — switch scope tab        (sc = s|u|g)
#   sx:nav:<sc>:<key> — open a choice picker for one setting
#   sx:tog:<sc>:<key> — toggle a bool setting
#   sx:set:<sc>:<key>:<val> — apply a value (edit_role RE-CHECKED server-side)
#   sx:close
# This SUPERSEDES the bespoke per-setting wiring where it maps cleanly (model /
# effort / permissions / memory / sandbox / language); the Tools grid and the
# Users admin remain their own pages, linked from the hub (NOT folded in).
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
    """The bare display name for a registry setting, derived from its ``name_key``
    row by dropping the trailing value-placeholder + chevron (e.g. "🧠 Model: {val}
    ▸" → "🧠 Model", "🌐 Language: {name} ▸" → "🌐 Language"). The row keys carry a
    `{val}`/`{name}` slot for the OLD single-page menu; here we only want the label."""
    raw = i18n.t(setting.name_key, lang)
    # Drop a trailing ": {placeholder}" and any trailing " ▸" chevron.
    raw = re.sub(r":?\s*\{[^}]*\}\s*▸?\s*$", "", raw)
    return raw.rstrip(" ▸").strip()


def _scope_badge(scope, lang: str) -> str:
    """A short localized badge naming WHICH scope currently supplies a value."""
    return i18n.t({
        ss.Scope.SESSION: "settings.badge_session",
        ss.Scope.USER: "settings.badge_user",
        ss.Scope.GLOBAL: "settings.badge_global",
    }[scope], lang)


def _setting_value_label(setting, value, lang: str) -> str:
    """Human label for a resolved value: bool → on/off; model id → friendly alias;
    None → the localized 'default'/'unlimited'; else the raw value."""
    if value is None:
        if setting.key == "max_turns":
            return i18n.t("maxturns.unlimited", lang)
        return i18n.t("settings.val_default", lang)
    if setting.type is bool:
        return i18n.onoff(bool(value), lang)
    if setting.key == "model":
        return MODEL_ID_TO_ALIAS.get(value, value)
    if setting.key == "permission_mode":
        return PERM_MODE_TO_NAME.get(value, value)
    if setting.key == "language":
        return i18n.lang_name(value)
    return str(value)


def _setting_choice_labels(setting, lang: str) -> list[tuple[str, str]]:
    """[(callback_value, button_label)] for a fixed-choice setting's picker."""
    if setting.key == "model":
        return [(a, a) for a in ("opus", "sonnet", "haiku")]
    if setting.key == "effort":
        return [(lv, lv) for lv in EFFORT_LEVELS] + [("default", i18n.t("settings.val_default", lang))]
    if setting.key == "permission_mode":
        return [(PERM_MODE_TO_NAME.get(m, m), PERM_MODE_TO_NAME.get(m, m))
                for m in ("default", "acceptEdits", "plan", "bypassPermissions")]
    if setting.key == "language":
        return [(code, i18n.lang_name(code)) for code in i18n.LANGUAGES]
    if setting.key == "max_turns":
        # A free integer in /maxturns; the hub offers sensible presets + unlimited.
        return [("10", "10"), ("25", "25"), ("50", "50"), ("100", "100"),
                ("default", i18n.t("maxturns.unlimited", lang))]
    # Fallback: render the raw choices.
    return [(str(c), str(c)) for c in (setting.choices or ())]


def _ss_tools_keyboard(state, lang: str = "en") -> InlineKeyboardMarkup:
    """Per-session Tools grid for the unified hub (#129/#141): one ✅/⬜ toggle per
    tool in the session's universe (chat → web tools, code → full toolset), then
    Back → the hub. Replaces the old st: tools page."""
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
    """Usage-display picker for the unified hub (owner; #147): off/footer/pinned/both
    (✓ on the current), then Back → the hub. Replaces the old st: admin→usage page."""
    B = InlineKeyboardButton
    btns = [B(text=_mark(m, cur), callback_data=f"sx:usageset:{m}")
            for m in ("off", "footer", "pinned", "both")]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
    rows.append([B(text=i18n.t("btn.back", lang), callback_data="sx:tab:s")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _access_label(access, lang: str = "en") -> str:
    """Localized label for an Access level (Delegated / Read-only / Hidden; #151)."""
    return i18n.t({
        ss.Access.DELEGATED: "settings.access_delegated",
        ss.Access.READONLY: "settings.access_readonly",
        ss.Access.HIDDEN: "settings.access_hidden",
    }[access], lang)


def _ss_option_admin_kb(setting, ctx, lang: str = "en") -> InlineKeyboardMarkup:
    """Owner OPTION-ADMIN page (Global tab → a setting; #151, menu.md §4.4): edit the
    GLOBAL value and the BASE access (Hidden / Read-only / Delegated). Per-user
    exceptions live on the user card (👥 Users). Back → the Global tab."""
    B = InlineKeyboardButton
    rows: list[list[InlineKeyboardButton]] = []
    if setting.set.get(ss.Scope.GLOBAL) is not None:
        gval, _ = ss.resolve_from(setting, ctx, ss.Scope.GLOBAL)
        vlabel = _setting_value_label(setting, gval, lang)
        cbv = (f"sx:tog:g:{setting.key}" if setting.type is bool
               else f"sx:nav:g:{setting.key}")
        rows.append([B(text=i18n.t("settings.opt_value", lang, val=vlabel), callback_data=cbv)])
    acc_label = _access_label(ss.configured_base_access(setting, ctx), lang)
    rows.append([B(text=i18n.t("settings.opt_access", lang, val=acc_label),
                   callback_data=f"sx:acc:{setting.key}")])
    rows.append([B(text=i18n.t("btn.back", lang), callback_data="sx:tab:g")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ss_access_kb(setting, ctx, lang: str = "en") -> InlineKeyboardMarkup:
    """Base-access picker for one option (owner; #151): Delegated / Read-only / Hidden
    (✓ on the current), Back → the option-admin page."""
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
    """Render a tiny unicode sparkline from utilization fractions (0..1).

    Non-numeric points (the CLI often omits utilization) are skipped. Returns ""
    when fewer than 2 numeric points exist, so /status only shows a trend when
    there is something meaningful to show.
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
    """Format an epoch timestamp as YYYY-MM-DD ("?" on bad input)."""
    try:
        return f"{datetime.fromtimestamp(float(ts)):%Y-%m-%d}"
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def _fmt_tokens(n) -> str:
    """Compact, Claude-Code-style token count: 12345 -> "12.3k", 1.2M, etc.

    Sub-1000 values are shown as-is; thousands/millions are abbreviated with one
    decimal, dropping a trailing ".0" so it reads cleanly ("15k", not "15.0k").
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
    """Parse a human token amount ('500k', '2m', '500000', '1.5M') → int, or None
    if it is not a usable non-negative number. Underscores/commas/spaces ignored."""
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
    """Compact rolling-cap display for the per-user views: the localized 'unlimited'
    glyph when uncapped, else the present windows as 'd:500k w:2m'."""
    rate = rate or {}
    parts = []
    if rate.get("day") is not None:
        parts.append("d:" + _fmt_tokens(rate["day"]))
    if rate.get("week") is not None:
        parts.append("w:" + _fmt_tokens(rate["week"]))
    return " ".join(parts) if parts else i18n.t("users.unlimited", lang)


# The full per-user tool-cap universe (#131): every tool a user could use across
# chat + code, in a stable order. The owner toggles which of these a user may use.
ALL_TOOLS: list[str] = list(engine.CHAT_TOOLS) + [
    t for t in engine.CODE_TOOLS if t not in engine.CHAT_TOOLS
]


def _fmt_cap(cap, lang: str = "en") -> str:
    """Tool-cap summary for the per-user card: localized 'all' when uncapped (None),
    else 'N/total' allowed tools."""
    if cap is None:
        return i18n.t("usercard.cap_all", lang)
    return f"{len(cap)}/{len(ALL_TOOLS)}"


def _tool_scope_label(tool: str, lang: str = "en") -> str:
    """Which session types a tool applies to, shown on the toggle button: the web
    tools run in CHAT and CODE; everything else is CODE only (needs a working dir)."""
    return i18n.t("tool.scope_both" if tool in engine.CHAT_TOOLS else "tool.scope_code", lang)


def _cu(obj: object, *names: str):
    """Read the first present field from a dict OR an attribute object.

    The SDK's get_context_usage() returns a ContextUsageResponse TypedDict
    (a dict subclass), so its fields are dict keys, not attributes — a plain
    getattr() would always miss them. This tolerates both shapes (and None):
    for a dict we try keys, otherwise getattr, returning the first non-None
    value found, or None if none of the names are present.
    """
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _format_rate(rate: object, lang: str = "en") -> str:
    """Render a RateLimitInfo snapshot into a compact (localized) status line.

    Tolerates missing/None attributes; returns "" if nothing useful is present.
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
