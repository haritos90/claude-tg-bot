"""Localization (l10n) for the bot's OWN user-facing strings.

English ("en") is the CANONICAL source locale: AGENTS.md golden rule #1 says the
repo may be released publicly, so the English column must always be complete.
Other locales are translation layers on top — adding a language is just adding a
column to LANGUAGES and filling that column in CATALOG (missing entries fall back
to English at lookup time, so a half-translated locale never crashes the bot).

Scope is the bot's INTERFACE only — command replies, menus, buttons, errors,
confirmations. Claude's actual answers are NOT translated here; the model already
mirrors the user's language. Code, comments, docstrings and the docs stay
English; the Russian text below is *data*, not source identifiers.

The per-user choice (which column to use) is auto-detected from the Telegram
client `language_code` on first contact, persisted in the DB, and overridable via
/language or /settings. The resolved choice is cached here per user id so the hot
path never hits the DB.
"""

from __future__ import annotations

# Canonical source locale; used as the fallback whenever a key lacks a
# translation in the requested locale.
DEFAULT_LANG = "en"

# Supported locales -> their display name, each written in its own language
# (shown in the /language picker). Extend this and add the matching column to
# every CATALOG row to support another language.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "ru": "Русский",
}


def normalize_lang(code: str | None) -> str:
    """Map a Telegram `language_code` ('ru', 'ru-RU', 'en-US', None) to a
    supported locale, falling back to DEFAULT_LANG for anything unknown."""
    if not code:
        return DEFAULT_LANG
    base = str(code).split("-", 1)[0].strip().lower()
    return base if base in LANGUAGES else DEFAULT_LANG


# --------------------------------------------------------------------------- #
# Per-user language cache (resolved once per user, by LanguageMiddleware).
# --------------------------------------------------------------------------- #
_user_lang: dict[int, str] = {}


def has_lang(user_id: int) -> bool:
    """True iff this user's locale has already been resolved this process."""
    return user_id in _user_lang


def cached_lang(user_id: int) -> str:
    """Return the user's resolved locale, or DEFAULT_LANG if not yet resolved."""
    return _user_lang.get(user_id, DEFAULT_LANG)


def remember_lang(user_id: int, lang: str) -> None:
    """Cache a user's locale (validated against LANGUAGES)."""
    _user_lang[user_id] = lang if lang in LANGUAGES else DEFAULT_LANG


def forget_lang(user_id: int) -> None:
    """Drop a cached locale (e.g. after an explicit change forces a re-read)."""
    _user_lang.pop(user_id, None)


# --------------------------------------------------------------------------- #
# The l10n table. Rows = message keys; columns = languages. Every row MUST have
# an "en" entry. HTML tags and {placeholders} must match across columns.
# --------------------------------------------------------------------------- #
CATALOG: dict[str, dict[str, str]] = {
    # -- common atoms ------------------------------------------------------- #
    "common.error": {"en": "Error.", "ru": "Ошибка."},
    "common.switched": {"en": "Switched.", "ru": "Переключено."},
    "common.created": {"en": "Created.", "ru": "Создано."},
    "common.deleted": {"en": "Deleted.", "ru": "Удалено."},
    "common.cancelled": {"en": "Cancelled.", "ru": "Отменено."},
    "common.nothing_cancel": {"en": "Nothing to cancel.", "ru": "Нечего отменять."},
    "common.on": {"en": "on", "ru": "вкл"},
    "common.off": {"en": "off", "ru": "выкл"},
    "common.yes": {"en": "yes", "ru": "да"},
    "common.no": {"en": "no", "ru": "нет"},
    "common.none_paren": {"en": "(none)", "ru": "(нет)"},
    "common.owner_only_access": {
        "en": "Only the owner can manage access.",
        "ru": "Управлять доступом может только владелец.",
    },
    "common.code_only": {
        "en": "This command is only available in <b>code</b> sessions.",
        "ru": "Эта команда доступна только в <b>код</b>-сессиях.",
    },
    "common.owner_only_usage": {
        "en": "Only the owner can change the usage display.",
        "ru": "Менять отображение расхода может только владелец.",
    },
    "common.favorited": {"en": "⭐ Added to favorites.", "ru": "⭐ Добавлено в избранное."},
    "common.unfavorited": {"en": "Removed from favorites.", "ru": "Убрано из избранного."},

    # -- generic buttons ---------------------------------------------------- #
    "btn.back": {"en": "◂ Back", "ru": "◂ Назад"},
    "btn.close": {"en": "✖ Close", "ru": "✖ Закрыть"},
    "btn.cancel": {"en": "✖ Cancel", "ru": "✖ Отмена"},
    "btn.search": {"en": "🔍 Search", "ru": "🔍 Поиск"},
    "btn.delete": {"en": "🗑 Delete", "ru": "🗑 Удалить"},
    "btn.clear_all": {"en": "🗑 Clear all", "ru": "🗑 Очистить всё"},
    "btn.prev": {"en": "◂ Prev", "ru": "◂ Назад"},
    "btn.next": {"en": "Next ▸", "ru": "Далее ▸"},
    "btn.chat": {"en": "💬 Chat", "ru": "💬 Чат"},
    "btn.upgrade_code": {"en": "🟩 Convert to code", "ru": "🟩 Сделать кодом"},
    "btn.downgrade_chat": {"en": "💬 Convert to chat", "ru": "💬 Сделать чатом"},
    "btn.code": {"en": "🟩 Code", "ru": "🟩 Код"},
    "btn.stop": {"en": "⏹ Stop", "ru": "⏹ Стоп"},
    # -- /sessions per-session options menu + browser actions (#95) --------- #
    "btn.switch": {"en": "✅ Switch", "ru": "✅ Переключиться"},
    "btn.recap": {"en": "📋 Recap", "ru": "📋 Сводка"},
    "btn.status": {"en": "ℹ️ Status", "ru": "ℹ️ Статус"},
    "btn.rename": {"en": "✏️ Rename", "ru": "✏️ Переименовать"},
    "btn.export": {"en": "📄 Export", "ru": "📄 Экспорт"},
    "btn.transcript": {"en": "📄 Transcript", "ru": "📄 Транскрипт"},
    "btn.export_files": {"en": "📦 Export files", "ru": "📦 Экспорт файлов"},
    "btn.favorite": {"en": "⭐ Favorite", "ru": "⭐ В избранное"},
    "btn.unfavorite": {"en": "☆ Unfavorite", "ru": "☆ Из избранного"},
    "btn.new_chat": {"en": "💬 New chat", "ru": "💬 Новый чат"},
    "btn.new_code": {"en": "🟩 New code", "ru": "🟩 Новый код"},

    # -- session mode words / taglines -------------------------------------- #
    "mode.word_chat": {"en": "chat", "ru": "чат"},
    "mode.word_code": {"en": "code", "ru": "код"},
    "mode.tagline_chat": {
        "en": "{glyph} <b>Chat</b> — a plain, tool-free conversation with Claude.",
        "ru": "{glyph} <b>Чат</b> — обычный разговор с Claude без инструментов.",
    },
    "mode.tagline_code": {
        "en": "{glyph} <b>Code</b> — a Claude Code agent that runs tools and edits "
              "files.{where}",
        "ru": "{glyph} <b>Код</b> — агент Claude Code: запускает инструменты и "
              "правит файлы.{where}",
    },
    # Terminal-style prompt line appended to the code tagline when a cwd is known.
    "mode.tagline_where": {
        "en": "\n<code>{cwd} $</code>",
        "ru": "\n<code>{cwd} $</code>",
    },

    # -- /help, /start ------------------------------------------------------ #
    # #148: /help is GENERATED from the command registry (commands.COMMANDS, grouped
    # by help_group) so it can't drift from the menu. i18n carries only the intro
    # blurb, the per-group headers, and the footer; the command lines come from the
    # registry labels. (The old hand-written help.text command list is retired.)
    "help.intro": {
        "en": (
            "<b>Your personal Claude &amp; Claude Code in Telegram</b>\n"
            "\n"
            "The bot keeps <b>named sessions</b> you switch between — each fully "
            "isolated (histories never cross). A session is born a <b>💬 chat</b> and "
            "can be promoted to <b>🟩 code</b> (a Claude Code agent with tools and a "
            "working directory) with /code, and back with /chat — the conversation "
            "carries across.\n"
            "\n"
            "Just send a message to talk in the current session; messages sent while a "
            "reply runs are queued and run next in the SAME session. Send a <b>photo</b>, "
            "<b>PDF</b>, or <b>text/code file</b> and the caption becomes the prompt."
        ),
        "ru": (
            "<b>Ваш личный Claude и Claude Code в Telegram</b>\n"
            "\n"
            "Бот хранит <b>именованные сессии</b>, между которыми вы переключаетесь — "
            "каждая полностью изолирована (истории не пересекаются). Сессия создаётся "
            "как <b>💬 чат</b> и может быть повышена до <b>🟩 кода</b> (агент Claude Code "
            "с инструментами и рабочей папкой) командой /code и обратно командой /chat — "
            "разговор переносится.\n"
            "\n"
            "Просто отправьте сообщение в текущую сессию; сообщения во время ответа "
            "ставятся в очередь и выполняются следующими в ТОЙ ЖЕ сессии. Отправьте "
            "<b>фото</b>, <b>PDF</b> или <b>текстовый/кодовый файл</b> — подпись станет запросом."
        ),
    },
    "help.footer": {
        "en": (
            "Open <b>/settings</b> to change model, effort, permissions and more. In "
            "code mode, dangerous tools (Bash, Write, Edit) ask for an inline "
            "Allow/Deny tap unless full-access is on."
        ),
        "ru": (
            "Откройте <b>/settings</b>, чтобы менять модель, усилие, права и другое. В "
            "режиме кода опасные инструменты (Bash, Write, Edit) спрашивают "
            "подтверждение, если не включён полный доступ."
        ),
    },
    "help.group_sessions": {"en": "<b>Sessions</b>", "ru": "<b>Сессии</b>"},
    "help.group_settings": {"en": "<b>Settings</b>", "ru": "<b>Настройки</b>"},
    "help.group_run": {"en": "<b>Run control</b>", "ru": "<b>Управление запуском</b>"},
    "help.group_code": {"en": "<b>Code mode</b>", "ru": "<b>Режим кода</b>"},
    "help.group_meta": {"en": "<b>Meta</b>", "ru": "<b>Прочее</b>"},
    "help.group_owner": {"en": "<b>Owner</b>", "ru": "<b>Владелец</b>"},

    # -- /language ---------------------------------------------------------- #
    "lang.title": {
        "en": "🌐 <b>Language</b>\nCurrent: <b>{name}</b>\nTap to change:",
        "ru": "🌐 <b>Язык</b>\nТекущий: <b>{name}</b>\nНажмите, чтобы изменить:",
    },
    "lang.set": {
        "en": "🌐 Interface language set to <b>{name}</b>.",
        "ru": "🌐 Язык интерфейса: <b>{name}</b>.",
    },
    "lang.row": {"en": "🌐 Language: {name} ▸", "ru": "🌐 Язык: {name} ▸"},

    # -- /settings ---------------------------------------------------------- #
    "settings.open_error": {
        "en": "Could not open settings: {err}",
        "ru": "Не удалось открыть настройки: {err}",
    },
    "settings.closed": {"en": "⚙️ Settings closed.", "ru": "⚙️ Настройки закрыты."},
    "settings.header": {
        "en": (
            "⚙️ <b>Settings</b>\n"
            "Type: <b>{mode}</b> <i>(/code · /chat to switch)</i> · "
            "Model: <code>{model}</code>\n"
            "{perm_line}Usage: <b>{usage}</b>\n"
            "Memory: <b>{memory}</b>\n"
            "Language: <b>{language}</b>\n\n"
            "Tap to change."
        ),
        "ru": (
            "⚙️ <b>Настройки</b>\n"
            "Тип: <b>{mode}</b> <i>(/code · /chat для смены)</i> · "
            "Модель: <code>{model}</code>\n"
            "{perm_line}Использование: <b>{usage}</b>\n"
            "Память: <b>{memory}</b>\n"
            "Язык: <b>{language}</b>\n\n"
            "Нажмите, чтобы изменить."
        ),
    },
    "settings.perm_seg": {
        "en": "Permissions: <b>{perm}</b> <i>(code)</i> · ",
        "ru": "Права: <b>{perm}</b> <i>(код)</i> · ",
    },
    "settings.row_model": {"en": "🧠 Model: {val} ▸", "ru": "🧠 Модель: {val} ▸"},
    "settings.row_tools": {"en": "🧰 Tools ▸", "ru": "🧰 Инструменты ▸"},
    "settings.row_effort": {"en": "⚡ Effort: {val} ▸", "ru": "⚡ Усилие: {val} ▸"},
    "tool.scope_both": {"en": "chat + code", "ru": "чат + код"},
    "tool.scope_code": {"en": "code", "ru": "код"},
    "settings.row_users": {"en": "👥 Users ▸", "ru": "👥 Пользователи ▸"},
    "settings.row_admin": {"en": "👑 Admin ▸", "ru": "👑 Админ ▸"},
    # #178 + owner Admin hub: the /settings → Admin sub-page (archive retention,
    # global owner toggles, and user-management command launchers).
    "admin.title": {"en": "👑 <b>Admin</b>\nOwner controls and archive retention.",
                    "ru": "👑 <b>Администрирование</b>\nНастройки владельца и хранение архивов."},
    "admin.retention": {"en": "🗄 Archive retention: {val} ▸",
                        "ru": "🗄 Хранение архивов: {val} ▸"},
    "admin.retention_title": {
        "en": "🗄 <b>Archive retention</b>\nPurge deleted-session archives older than:",
        "ru": "🗄 <b>Хранение архивов</b>\nУдалять архивы удалённых сессий старше:"},
    "admin.ret_saved": {"en": "✓ Archive retention: {val}", "ru": "✓ Хранение архивов: {val}"},
    "admin.gsl_btn": {"en": "🔢 Sessions/user: {val} ▸", "ru": "🔢 Сессий/польз.: {val} ▸"},
    "admin.gsl_prompt": {
        "en": "Send the GLOBAL default session limit per user (a number, e.g. <code>10</code>, "
              "or <code>off</code> for unlimited). /cancel to abort.",
        "ru": "Отправьте ГЛОБАЛЬНЫЙ лимит сессий на пользователя (число, напр. <code>10</code>, "
              "или <code>off</code> для безлимита). /cancel — отмена.",
    },
    "admin.gsl_saved": {"en": "✓ Global session limit: {val} per user.",
                        "ru": "✓ Глобальный лимит сессий: {val} на пользователя."},
    "admin.ret_never": {"en": "♾ Never (keep forever)", "ru": "♾ Никогда (хранить всегда)"},
    "admin.ret_1mo": {"en": "1 month", "ru": "1 месяц"},
    "admin.ret_3mo": {"en": "3 months", "ru": "3 месяца"},
    "admin.ret_6mo": {"en": "6 months", "ru": "6 месяцев"},
    "admin.ret_12mo": {"en": "12 months", "ru": "12 месяцев"},
    "admin.ret_days": {"en": "{n} days", "ru": "{n} дн."},
    "admin.tog_codesplit": {"en": "🧩 Code split: {val}", "ru": "🧩 Разбивка кода: {val}"},
    "admin.tog_workingplate": {"en": "⏳ Working plate: {val}", "ru": "⏳ Плашка работы: {val}"},
    "admin.btn_allow": {"en": "➕ Allow", "ru": "➕ Разрешить"},
    "admin.btn_deny": {"en": "➖ Deny", "ru": "➖ Удалить"},
    "admin.btn_level": {"en": "🎚 Level", "ru": "🎚 Уровень"},
    "admin.btn_expire": {"en": "⏳ Expiry", "ru": "⏳ Срок"},
    "admin.btn_limit": {"en": "💳 Tokens", "ru": "💳 Токены"},
    "admin.btn_userstats": {"en": "📊 Stats", "ru": "📊 Статистика"},
    "settings.back_to": {"en": "◂ Settings", "ru": "◂ Настройки"},
    "settings.saved": {"en": "✓ Saved", "ru": "✓ Сохранено"},
    "settings.row_perm": {"en": "🔐 Permissions: {val} ▸", "ru": "🔐 Права: {val} ▸"},
    "settings.row_usage": {"en": "📊 Usage: {val} ▸", "ru": "📊 Использование: {val} ▸"},
    # #164: warm-cache post-reply note (delegated) + auto-compact (owner/hidden).
    "settings.row_hot_cache_timer": {"en": "🔥 Warm-cache note: {val}", "ru": "🔥 Заметка о тёплом кэше: {val}"},
    "settings.row_auto_compact": {"en": "📦 Auto-compact: {val}", "ru": "📦 Автокомпакт: {val}"},
    "settings.row_ctx_status": {"en": "🧠 Live context size: {val}", "ru": "🧠 Размер контекста в плашке: {val}"},
    "stream.context": {"en": "🧠 context {n}", "ru": "🧠 контекст {n}"},
    # #147: bare name for the usage-display picker title (sx: hub sub-page).
    "settings.usage_name": {"en": "📊 Usage display", "ru": "📊 Использование"},
    # #141: header for the per-session Tools grid ported onto the sx: hub.
    "settings.tools_title": {
        "en": "🧰 <b>Tools</b>\nToggle the tools this session may use.",
        "ru": "🧰 <b>Инструменты</b>\nВключите инструменты, доступные этой сессии.",
    },
    # #151 access model (menu.md §4): owner option-admin page + access levels.
    "settings.access_delegated": {"en": "Delegated", "ru": "Делегировано"},
    "settings.access_readonly": {"en": "Read-only", "ru": "Только чтение"},
    "settings.access_hidden": {"en": "Hidden", "ru": "Скрыто"},
    "settings.opt_value": {"en": "📝 Global value: {val} ▸", "ru": "📝 Глобальное значение: {val} ▸"},
    "settings.opt_access": {"en": "🔑 Base access: {val} ▸", "ru": "🔑 Базовый доступ: {val} ▸"},
    "settings.opt_title": {
        "en": "⚙️ <b>{name}</b>\nSet the global value and who may see/change it.",
        "ru": "⚙️ <b>{name}</b>\nЗадайте глобальное значение и кто может видеть/менять его.",
    },
    "settings.acc_title": {
        "en": "🔑 <b>{name} — access</b>\nDelegated: users change it · Read-only: they "
              "see it · Hidden: they don't. Per-user exceptions live on the user card.",
        "ru": "🔑 <b>{name} — доступ</b>\nДелегировано: пользователи меняют · Только "
              "чтение: видят · Скрыто: нет. Исключения по пользователю — в карточке.",
    },
    "settings.ro_toast": {
        "en": "Read-only — the owner hasn't delegated this setting to you.",
        "ru": "Только чтение — владелец не делегировал вам эту настройку.",
    },
    "settings.row_streaming": {"en": "Streaming: {val}", "ru": "Стриминг: {val}"},
    # #154: 🗄 is the canonical memory/context emoji (🧠 is reserved for MODEL).
    "settings.row_memory": {"en": "🗄 Big memory: {val}", "ru": "🗄 Большая память: {val}"},
    # #140-fix: dedicated max_turns label (was reusing settings.row_model, which
    # rendered TWO "🧠 Model" rows in the registry-driven /settings hub).
    "settings.row_maxturns": {"en": "🔁 Max turns: {val} ▸", "ru": "🔁 Лимит ходов: {val} ▸"},
    # #138: sandbox is OWNER-ONLY and hidden from non-owners in /settings.
    # #154: 🧪 is the canonical sandbox emoji (📦 is reserved for file export).
    "settings.row_sandbox": {"en": "🧪 Sandbox: {val} ▸", "ru": "🧪 Песочница: {val} ▸"},
    # #138 PART 2: the registry-driven, scope-tabbed /settings hub.
    "settings.tab_session": {"en": "📍 This session", "ru": "📍 Эта сессия"},
    "settings.tab_user": {"en": "👤 My defaults", "ru": "👤 Мои умолчания"},
    "settings.tab_global": {"en": "🌍 Global", "ru": "🌍 Глобально"},
    # Short source badges shown next to a resolved value (which scope supplies it).
    "settings.badge_session": {"en": "this session", "ru": "эта сессия"},
    "settings.badge_user": {"en": "my default", "ru": "моё умолчание"},
    "settings.badge_global": {"en": "global default", "ru": "глобально"},
    "settings.v2_header": {
        "en": "⚙️ <b>Settings</b> · {tab}\nTap a setting to change it.",
        "ru": "⚙️ <b>Настройки</b> · {tab}\nНажмите настройку, чтобы изменить её.",
    },
    # One hub row: name, resolved value, and the badge of its source scope.
    "settings.v2_row": {
        "en": "{name}: {val} · {badge} ▸",
        "ru": "{name}: {val} · {badge} ▸",
    },
    "settings.v2_pick": {
        "en": "⚙️ <b>{name}</b>\nPick a value.",
        "ru": "⚙️ <b>{name}</b>\nВыберите значение.",
    },
    "settings.val_default": {"en": "default", "ru": "по умолчанию"},
    "settings.denied": {
        "en": "Not allowed.",
        "ru": "Недоступно.",
    },

    # -- session create / switch / rename / delete -------------------------- #
    "session.created": {
        "en": "Created {glyph} <b>{name}</b> and switched to it.\n{tagline}\n"
              "Send a message to start · /rename to rename · /sessions to switch.",
        "ru": "Создана {glyph} <b>{name}</b>, переключаемся на неё.\n{tagline}\n"
              "Отправьте сообщение, чтобы начать · /rename — переименовать · "
              "/sessions — переключиться.",
    },
    # #143: session.new_pick is DEAD — the /new chat/code chooser was removed in
    # #133 (every session is born a chat and is promotable via /code), and its
    # on_new_cb handler is commented out. Row removed (restore alongside the chooser).
    # "session.new_pick": {
    #     "en": "Create a new session — pick the type ...:\n{tagline_chat}\n{tagline_code}",
    #     "ru": "Создать новую сессию — выберите тип ...:\n{tagline_chat}\n{tagline_code}",
    # },
    "session.renamed": {
        "en": "Session renamed to <b>{name}</b>.",
        "ru": "Сессия переименована в <b>{name}</b>.",
    },
    "session.rename_prompt": {
        "en": "✏️ Send the new session name (or /cancel).",
        "ru": "✏️ Отправьте новое имя сессии (или /cancel).",
    },
    "session.default_name_chat": {"en": "Chat session", "ru": "Чат-сессия"},
    "session.default_name_code": {"en": "Code session", "ru": "Код-сессия"},
    "session.first_default": {"en": "Session 1", "ru": "Сессия 1"},
    "session.fork_name": {"en": "{base} (fork)", "ru": "{base} (форк)"},
    "session.limit_reached": {
        "en": "🔢 You've reached your session limit (<b>{total}/{cap}</b>). Delete a session "
              "or <code>/clear</code> one to reuse it (see <code>/sessions</code>), then try again.",
        "ru": "🔢 Достигнут лимит сессий (<b>{total}/{cap}</b>). Удалите сессию или очистите её "
              "через <code>/clear</code>, чтобы переиспользовать (см. <code>/sessions</code>), затем повторите.",
    },
    "session.limit_reached_short": {
        "en": "Session limit reached — delete or /clear one first.",
        "ru": "Достигнут лимит сессий — удалите или очистите одну.",
    },
    "session.cleared": {"en": "Session cleared.", "ru": "Сессия очищена."},
    "session.clear_error": {
        "en": "Could not fully clear the session: {err}",
        "ru": "Не удалось полностью очистить сессию: {err}",
    },
    "session.switched_to": {
        "en": "✅ Switched to {glyph} <b>{name}</b>",
        "ru": "✅ Переключено на {glyph} <b>{name}</b>",
    },
    "session.card_meta": {
        "en": "<code>{sid}</code> · Model: <code>{model}</code> · {date} · {reqs} msgs · {toks} tok",
        "ru": "<code>{sid}</code> · Модель: <code>{model}</code> · {date} · {reqs} сообщ. · {toks} ток.",
    },
    "session.delete_confirm": {
        "en": "Delete session <b>{name}</b>?\nThis permanently removes its "
              "history and code working files.",
        "ru": "Удалить сессию <b>{name}</b>?\nЭто навсегда удалит её историю и "
              "рабочие файлы кода.",
    },
    "session.delete_failed": {
        "en": "Couldn't delete that session — it may already be gone.",
        "ru": "Не удалось удалить эту сессию — возможно, она уже удалена.",
    },

    # -- /sessions browser -------------------------------------------------- #
    "sessions.head_dm": {"en": "🗂 <b>Your sessions</b>", "ru": "🗂 <b>Ваши сессии</b>"},
    "sessions.head_group": {"en": "🗂 <b>Topics</b>", "ru": "🗂 <b>Темы</b>"},
    "sessions.head_search": {"en": " · search “{kw}”", "ru": " · поиск «{kw}»"},
    "sessions.head_total": {"en": " · {total} total", "ru": " · всего {total}"},
    "sessions.row": {
        # #136: dropped the leading <code>{sid}</code> — the public id is noise to
        # the user; the list now leads with the icon + name.
        # #211: dropped {mode}/{date} too — the icon already conveys the mode and the
        # date is list noise. was: "{icon} <b>{name}</b> — {mode} · {date}{mark}"
        "en": "{icon} <b>{name}</b>{mark}",
        "ru": "{icon} <b>{name}</b>{mark}",
    },
    "sessions.row_stats": {
        "en": "    {reqs} msgs · {toks} tok",
        "ru": "    {reqs} сообщ. · {toks} ток.",
    },
    "sessions.options_header": {
        "en": "{glyph} <b>{name}</b> — choose an action:",
        "ru": "{glyph} <b>{name}</b> — выберите действие:",
    },
    "sessions.current_mark": {"en": " ⬅️ current", "ru": " ⬅️ текущая"},
    "sessions.none_match": {
        "en": "<i>(no sessions match)</i>",
        "ru": "<i>(нет подходящих сессий)</i>",
    },
    "sessions.search_prompt": {
        "en": "🔍 Send a keyword to search your sessions (or /cancel).",
        "ru": "🔍 Отправьте слово для поиска по вашим сессиям (или /cancel).",
    },
    "sessions.search_toast": {"en": "Type a keyword.", "ru": "Введите слово."},

    # -- /mode -------------------------------------------------------------- #
    # #220: mode.show / mode.hint_upgrade / mode.hint_downgrade removed — they were the
    # pre-#218 "show current mode + how to switch" copy; /mode now toggles the type
    # directly (#218a), so nothing rendered them (dead-key cleanup).
    "mode.upgraded": {
        "en": "{glyph} <b>Upgraded to a code session.</b>{defer}\n{tagline}",
        "ru": "{glyph} <b>Повышено до код-сессии.</b>{defer}\n{tagline}",
    },
    "mode.downgraded": {
        "en": "{glyph} <b>Back to a chat session</b> — your files are kept.{defer}\n{tagline}",
        "ru": "{glyph} <b>Снова чат-сессия</b> — файлы сохранены.{defer}\n{tagline}",
    },
    "mode.already": {"en": "Already a <b>{mode}</b> session.", "ru": "Уже <b>{mode}</b>-сессия."},
    "mode.switched_toast": {"en": "Now a {mode} session.", "ru": "Теперь {mode}-сессия."},
    "session.upgrade_hint": {
        "en": "💡 This is a chat. Need to run code or edit files? Upgrade with /code.",
        "ru": "💡 Это чат. Нужно запускать код или править файлы? Повысьте через /code.",
    },

    # -- /model ------------------------------------------------------------- #
    "model.current": {
        "en": "Current model: <code>{model}</code>",
        "ru": "Текущая модель: <code>{model}</code>",
    },
    "model.set": {
        "en": "Model set to: <code>{model}</code>{defer}",
        "ru": "Модель установлена: <code>{model}</code>{defer}",
    },
    "model.pick": {
        "en": "Current model: <code>{model}</code>. Pick one:",
        "ru": "Текущая модель: <code>{model}</code>. Выберите:",
    },
    "common.defer_note": {
        "en": " <i>(applies after the current run finishes)</i>",
        "ru": " <i>(применится после завершения текущего запуска)</i>",
    },

    # -- /effort ------------------------------------------------------------ #
    "effort.default_label": {"en": "default (high)", "ru": "по умолчанию (high)"},
    "effort.show": {
        "en": "Reasoning effort: <b>{cur}</b>.\nSet with "
              "<code>/effort low|medium|high|xhigh|max</code> "
              "(<code>/effort default</code> to reset). Higher = deeper thinking, "
              "more tokens.",
        "ru": "Глубина рассуждений: <b>{cur}</b>.\nЗадайте через "
              "<code>/effort low|medium|high|xhigh|max</code> "
              "(<code>/effort default</code> — сброс). Выше = глубже мышление, "
              "больше токенов.",
    },
    "effort.reset": {
        "en": "Reasoning effort reset to default.{defer}",
        "ru": "Глубина рассуждений сброшена к значению по умолчанию.{defer}",
    },
    "effort.usage": {
        "en": "Usage: <code>/effort low|medium|high|xhigh|max</code>.",
        "ru": "Использование: <code>/effort low|medium|high|xhigh|max</code>.",
    },
    "effort.set": {
        "en": "Reasoning effort: <b>{val}</b>.{defer}",
        "ru": "Глубина рассуждений: <b>{val}</b>.{defer}",
    },
    "effort.pick": {
        "en": "Reasoning effort: <b>{cur}</b>. Pick one:",
        "ru": "Глубина рассуждений: <b>{cur}</b>. Выберите:",
    },

    # -- /files (read-only working-dir tree; #100) -------------------------- #
    # #136: show the session NAME, not the host path (was <code>{dir}</code>).
    "files.header": {"en": "📂 <b>{name}</b>", "ru": "📂 <b>{name}</b>"},
    "files.empty": {
        "en": "📂 <b>{name}</b> — no files yet.",
        "ru": "📂 <b>{name}</b> — пока нет файлов.",
    },

    # -- /export (zip the code-session working dir) ------------------------- #
    "export.empty": {
        "en": "📦 Nothing to export — the working directory is empty.",
        "ru": "📦 Нечего экспортировать — рабочая папка пуста.",
    },
    "export.too_big": {
        "en": "📦 The working directory is too large to export (max ~49 MB zipped).",
        "ru": "📦 Рабочая папка слишком большая для экспорта (макс. ~49 МБ в архиве).",
    },
    "export.caption": {
        "en": "📦 Working-directory files.",
        "ru": "📦 Файлы рабочей папки.",
    },

    # -- /sandbox (owner per-session isolation opt-out; #104) --------------- #
    "sandbox.show": {
        "en": "🧪 Sandbox for this session: <b>{state}</b> · global SANDBOX_CODE: "
              "<b>{glob}</b>.\n<code>/sandbox on|off</code> — run this code session "
              "with or without isolation (owner test).",
        "ru": "🧪 Песочница для этой сессии: <b>{state}</b> · глобально SANDBOX_CODE: "
              "<b>{glob}</b>.\n<code>/sandbox on|off</code> — запускать эту код-сессию "
              "с изоляцией или без (тест владельца).",
    },
    # #138 PART 2: sandbox shown with its RESOLVED value + the scope badge that
    # supplies it (replaces the confusing two-value sandbox.show line).
    "sandbox.show_scoped": {
        "en": "🧪 Sandbox: <b>{state}</b> <i>({scope})</i>.\n"
              "<code>/sandbox on|off</code> — run this code session with or without "
              "isolation (owner test).",
        "ru": "🧪 Песочница: <b>{state}</b> <i>({scope})</i>.\n"
              "<code>/sandbox on|off</code> — запускать эту код-сессию с изоляцией "
              "или без (тест владельца).",
    },
    "sandbox.set_on": {
        "en": "🧪 Sandbox <b>on</b> for this session — code runs isolated.{note}",
        "ru": "🧪 Песочница <b>вкл</b> для этой сессии — код выполняется в изоляции.{note}",
    },
    "sandbox.set_off": {
        "en": "🧪 Sandbox <b>off</b> for this session — code runs WITHOUT isolation "
              "(owner test).{note}",
        "ru": "🧪 Песочница <b>выкл</b> для этой сессии — код выполняется БЕЗ изоляции "
              "(тест владельца).{note}",
    },

    # -- /secret (per-session user-supplied service credentials; #119d) ----- #
    "secret.help": {
        "en": "🔐 <b>Session secrets</b>\nStored: {names}\n\nSend <code>NAME=VALUE</code> "
              "to add one (e.g. <code>GH_TOKEN=ghp_xxx</code>), or <code>/cancel</code>.\n"
              "Clear with <code>/secret clear</code> (all) or <code>/secret clear NAME</code> "
              "(one).\nSecrets are injected as environment variables into <b>this session's "
              "jail only</b> — not other sessions, and the owner's own credentials are never "
              "shared. Values are never shown again.",
        "ru": "🔐 <b>Секреты сессии</b>\nСохранено: {names}\n\nОтправьте <code>NAME=VALUE</code>, "
              "чтобы добавить (напр. <code>GH_TOKEN=ghp_xxx</code>), или <code>/cancel</code>.\n"
              "Очистить: <code>/secret clear</code> (все) или <code>/secret clear NAME</code> "
              "(один).\nСекреты внедряются как переменные окружения <b>только в jail этой "
              "сессии</b> — не в другие сессии, и учётные данные владельца никогда не "
              "передаются. Значения больше не показываются.",
    },
    "secret.stored": {
        "en": "🔐 Stored <code>{name}</code> for this session — injected into the jail on "
              "the next turn. The value is never shown again.",
        "ru": "🔐 Сохранено <code>{name}</code> для этой сессии — внедряется в jail на "
              "следующем ходе. Значение больше не показывается.",
    },
    "secret.cleared": {
        "en": "🔐 Removed {what} for this session.",
        "ru": "🔐 Удалено {what} для этой сессии.",
    },
    "secret.all": {"en": "all secrets", "ru": "все секреты"},
    "secret.none": {"en": "(none)", "ru": "(нет)"},
    "secret.bad_name": {
        "en": "🔐 Couldn't parse that. Send <code>NAME=VALUE</code> — NAME is letters, "
              "digits and underscores (e.g. <code>GH_TOKEN</code>) — or <code>/secret clear</code>.",
        "ru": "🔐 Не удалось разобрать. Отправьте <code>NAME=VALUE</code> — NAME из букв, "
              "цифр и подчёркиваний (напр. <code>GH_TOKEN</code>) — или <code>/secret clear</code>.",
    },

    # -- /maxturns ---------------------------------------------------------- #
    "maxturns.unlimited": {"en": "unlimited", "ru": "без ограничений"},
    "maxturns.show": {
        "en": "Max agentic turns: <b>{cur}</b>.\nSet with <code>/maxturns N</code> "
              "or <code>/maxturns off</code> (caps how many tool/response turns a "
              "code run may take).",
        "ru": "Макс. агентных ходов: <b>{cur}</b>.\nЗадайте через "
              "<code>/maxturns N</code> или <code>/maxturns off</code> (ограничивает "
              "число ходов инструмент/ответ в код-запуске).",
    },
    "maxturns.set_unlimited": {
        "en": "Max agentic turns: <b>unlimited</b>.{defer}",
        "ru": "Макс. агентных ходов: <b>без ограничений</b>.{defer}",
    },
    "maxturns.usage": {
        "en": "Usage: <code>/maxturns N</code> (1–1000) or <code>/maxturns off</code>.",
        "ru": "Использование: <code>/maxturns N</code> (1–1000) или "
              "<code>/maxturns off</code>.",
    },
    "maxturns.set": {
        "en": "Max agentic turns: <b>{n}</b>.{defer}",
        "ru": "Макс. агентных ходов: <b>{n}</b>.{defer}",
    },

    # -- /dirs -------------------------------------------------------------- #
    "dirs.list": {
        "en": "<b>Extra code directories</b>\n{shown}\n\n"
              "<code>/dirs add &lt;path&gt;</code> · <code>/dirs clear</code> "
              "(code sessions; paths must be absolute).",
        "ru": "<b>Дополнительные папки для кода</b>\n{shown}\n\n"
              "<code>/dirs add &lt;путь&gt;</code> · <code>/dirs clear</code> "
              "(код-сессии; пути должны быть абсолютными).",
    },
    "dirs.cleared": {
        "en": "Extra directories cleared.{defer}",
        "ru": "Дополнительные папки очищены.{defer}",
    },
    "dirs.need_absolute": {
        "en": "The path must be absolute, e.g. <code>/dirs add /srv/data</code>.",
        "ru": "Путь должен быть абсолютным, например <code>/dirs add /srv/data</code>.",
    },
    "dirs.sandbox_only": {
        "en": "Non-owner paths must be under your sandbox directory.",
        "ru": "Для не-владельца пути должны быть внутри вашей песочницы.",
    },
    "dirs.added": {
        "en": "Added <code>{path}</code>.{defer}",
        "ru": "Добавлено <code>{path}</code>.{defer}",
    },
    "dirs.usage": {
        "en": "Usage: <code>/dirs</code>, <code>/dirs add &lt;path&gt;</code>, or "
              "<code>/dirs clear</code>.",
        "ru": "Использование: <code>/dirs</code>, <code>/dirs add &lt;путь&gt;</code> "
              "или <code>/dirs clear</code>.",
    },

    # -- /fork -------------------------------------------------------------- #
    "fork.dm_only": {
        "en": "Forking is available for DM sessions.",
        "ru": "Форк доступен для сессий в личных сообщениях.",
    },
    "fork.no_session": {"en": "No session to fork.", "ru": "Нет сессии для форка."},
    "fork.empty": {
        "en": "This session has no conversation yet — nothing to fork. Send a "
              "message first, then /fork.",
        "ru": "В этой сессии ещё нет разговора — форкать нечего. Сначала отправьте "
              "сообщение, затем /fork.",
    },
    "fork.done": {
        "en": "🍴 Forked into {glyph} <b>{name}</b> and switched to it — it "
              "branches from here; the original is untouched. Send a message to "
              "continue the branch.",
        "ru": "🍴 Форк в {glyph} <b>{name}</b>, переключаемся на неё — ветвление "
              "отсюда; оригинал не тронут. Отправьте сообщение, чтобы продолжить "
              "ветку.",
    },

    # -- /memory ------------------------------------------------------------ #
    "memory.show": {
        "en": "Big memory: <b>{current}</b>.\nWhen <b>on</b>, this session requests "
              "the <b>1M-token</b> context window via the model's [1m] variant — active "
              "on <b>Opus</b> (auto-included on Max). On Sonnet 1M needs paid "
              "usage-credits and Haiku has no 1M, so it has no effect there. Your "
              "conversation persists across restarts either way. Toggle with "
              "<code>/memory on</code> / <code>/memory off</code>.",
        "ru": "Большая память: <b>{current}</b>.\nКогда <b>вкл</b>, эта сессия "
              "запрашивает окно контекста на <b>1M токенов</b> через [1m]-вариант "
              "модели — работает на <b>Opus</b> (включено на Max). На Sonnet для 1M "
              "нужны платные кредиты, а у Haiku 1M нет, так что там это ни на что не "
              "влияет. Разговор и так сохраняется между перезапусками. Переключение: "
              "<code>/memory on</code> / <code>/memory off</code>.",
    },
    "memory.usage": {
        "en": "Usage: <code>/memory on</code> or <code>/memory off</code>.",
        "ru": "Использование: <code>/memory on</code> или <code>/memory off</code>.",
    },
    "memory.already": {
        "en": "Big memory is already <b>{state}</b>.",
        "ru": "Большая память уже <b>{state}</b>.",
    },
    "memory.on": {
        "en": "Big memory <b>on</b> — on <b>Opus</b> this session now uses the 1M-token "
              "context window (on Sonnet/Haiku 1M isn't available, so context stays "
              "standard).{note}",
        "ru": "Большая память <b>вкл</b> — на <b>Opus</b> эта сессия теперь использует "
              "окно контекста на 1M токенов (на Sonnet/Haiku 1M недоступно, контекст "
              "остаётся стандартным).{note}",
    },
    "memory.off": {
        "en": "Big memory <b>off</b> — back to the standard context window.{note}",
        "ru": "Большая память <b>выкл</b> — назад к стандартному окну контекста.{note}",
    },

    # -- /cwd --------------------------------------------------------------- #
    "cwd.current": {
        "en": "Current working directory: <code>{cwd}</code>",
        "ru": "Текущая рабочая папка: <code>{cwd}</code>",
    },
    "cwd.owner_only": {
        "en": "Only the owner can set a directory outside the base working dir. "
              "Use a path inside it, e.g. <code>/cwd myproject</code>.",
        "ru": "Только владелец может задать папку вне базовой рабочей директории. "
              "Используйте путь внутри неё, например <code>/cwd myproject</code>.",
    },
    "cwd.mkdir_error": {
        "en": "Could not create the directory <code>{dir}</code>: {err}",
        "ru": "Не удалось создать папку <code>{dir}</code>: {err}",
    },
    "cwd.set": {
        "en": "Working directory (code mode): <code>{cwd}</code>{defer}",
        "ru": "Рабочая папка (режим кода): <code>{cwd}</code>{defer}",
    },

    # -- /permissions ------------------------------------------------------- #
    "perm.current": {
        "en": "Current code-mode permissions: <b>{current}</b>",
        "ru": "Текущие права режима кода: <b>{current}</b>",
    },
    "perm.policies_header": {"en": "<b>Policies:</b>", "ru": "<b>Политики:</b>"},
    "perm.line": {"en": "<code>{name}</code> — {help}", "ru": "<code>{name}</code> — {help}"},
    "perm.unknown": {
        "en": "Unknown policy. Use one of: {names}",
        "ru": "Неизвестная политика. Используйте одну из: {names}",
    },
    "perm.full_access_owner_only": {
        "en": "Only the owner can enable <b>full-access</b> (it bypasses every "
              "approval). Use <code>ask</code>, <code>auto-edits</code> or "
              "<code>plan</code>.",
        "ru": "Только владелец может включить <b>full-access</b> (он обходит все "
              "подтверждения). Используйте <code>ask</code>, "
              "<code>auto-edits</code> или <code>plan</code>.",
    },
    "perm.set_full_access": {
        "en": "Permissions set to <b>full-access</b>. ⚠️ This bypasses all approval "
              "and can run <b>anything</b> (Bash, Write, Edit) without asking. Use "
              "with care.{note}",
        "ru": "Права установлены в <b>full-access</b>. ⚠️ Это обходит все "
              "подтверждения и может выполнить <b>что угодно</b> (Bash, Write, Edit) "
              "без вопросов. Используйте осторожно.{note}",
    },
    "perm.set": {
        "en": "Permissions set to <b>{name}</b> — {help}.{note}",
        "ru": "Права установлены в <b>{name}</b> — {help}.{note}",
    },
    "perm.help.ask": {
        "en": "ask before every tool — Bash, Write, Edit, web (maximum oversight)",
        "ru": "спрашивать перед каждым инструментом — Bash, Write, Edit, web (максимальный контроль)",
    },
    "perm.help.auto-edits": {
        "en": "default — auto-run edits & safe commands; ask only for push, destructive or web/outbound actions",
        "ru": "по умолчанию — авто-запуск правок и безопасных команд; спрашивать только push, разрушительные и сетевые действия",
    },
    "perm.help.plan": {
        "en": "plan only, do not run tools",
        "ru": "только планирование, без запуска инструментов",
    },
    "perm.help.full-access": {
        "en": "bypass all approval — can run anything",
        "ru": "без подтверждений — может выполнить что угодно",
    },

    # -- /auto -------------------------------------------------------------- #
    "auto.owner_only": {
        "en": "Only the owner can toggle auto mode.",
        "ru": "Переключать авто-режим может только владелец.",
    },
    "auto.show": {
        "en": "Auto mode = a shortcut for <code>/permissions full-access</code> "
              "(run tools without asking): <b>{state}</b>.\nUse <code>/auto on</code> "
              "or <code>/auto off</code>.",
        "ru": "Авто-режим = сокращение для <code>/permissions full-access</code> "
              "(запуск инструментов без вопросов): <b>{state}</b>.\nИспользуйте "
              "<code>/auto on</code> или <code>/auto off</code>.",
    },
    "auto.usage": {
        "en": "Use <code>/auto on</code> or <code>/auto off</code>.",
        "ru": "Используйте <code>/auto on</code> или <code>/auto off</code>.",
    },
    "auto.on": {
        "en": "🚀 Auto mode <b>on</b> — code tools (Bash, Write, Edit) now run "
              "without asking. <code>/auto off</code> to re-arm approvals.{note}",
        "ru": "🚀 Авто-режим <b>вкл</b> — инструменты кода (Bash, Write, Edit) "
              "теперь запускаются без вопросов. <code>/auto off</code>, чтобы "
              "вернуть подтверждения.{note}",
    },
    "auto.off": {
        "en": "Auto mode <b>off</b> — dangerous tools ask again.{note}",
        "ru": "Авто-режим <b>выкл</b> — опасные инструменты снова спрашивают.{note}",
    },

    # -- /usage ------------------------------------------------------------- #
    "usage.current": {
        "en": "Current usage display: <b>{current}</b>",
        "ru": "Текущий показ использования: <b>{current}</b>",
    },
    "usage.modes_header": {"en": "<b>Modes:</b>", "ru": "<b>Режимы:</b>"},
    "usage.line": {"en": "<code>{name}</code> — {help}", "ru": "<code>{name}</code> — {help}"},
    "usage.unknown": {
        "en": "Unknown usage mode. Use one of: {names}",
        "ru": "Неизвестный режим использования. Используйте один из: {names}",
    },
    # --- #164: /limits (own / account), /userstats table, working-plate line,
    #     warm-cache note. ---
    "limits.header": {"en": "📊 <b>Your limits</b>", "ru": "📊 <b>Ваши лимиты</b>"},
    "limits.today": {"en": "Today", "ru": "Сегодня"},
    "limits.week": {"en": "This week", "ru": "За неделю"},
    "limits.requests": {"en": "Requests", "ru": "Запросов"},
    "limits.no_cap": {"en": "no cap", "ru": "без лимита"},
    "limits.sessions": {"en": "Sessions: <b>{used}</b> / {cap}", "ru": "Сессии: <b>{used}</b> / {cap}"},
    "limits.unlimited_word": {"en": "∞", "ru": "∞"},
    "limits.rolling_note": {
        "en": "<i>Windows are rolling (trailing 24h / 7d).</i>",
        "ru": "<i>Окна скользящие (последние 24ч / 7д).</i>",
    },
    "limits.units_note": {
        "en": "<i>Usage is in weighted units (cost-aware: model, output and cache); caps are in units too.</i>",
        "ru": "<i>Расход во взвешенных единицах (с учётом модели, вывода и кэша); лимиты тоже в единицах.</i>",
    },
    "limits.account_header": {
        "en": "📊 <b>Account usage</b> (subscription, owner)",
        "ru": "📊 <b>Использование аккаунта</b> (подписка, владелец)",
    },
    "limits.account_empty": {"en": "No account usage data yet.", "ru": "Пока нет данных аккаунта."},
    "userstats.title": {"en": "User statistics", "ru": "Статистика пользователей"},
    "userstats.empty": {"en": "👥 No usage recorded yet.", "ru": "👥 Пока нет записанного использования."},
    "userstats.col_user": {"en": "User", "ru": "Пользователь"},
    "userstats.col_day": {"en": "Day", "ru": "День"},
    "userstats.col_week": {"en": "Week", "ru": "Неделя"},
    "userstats.col_total": {"en": "Total", "ru": "Всего"},
    "userstats.col_req": {"en": "Req", "ru": "Запр"},
    "userstats.col_last": {"en": "Last", "ru": "Актив."},
    "stream.usage_line": {"en": "📊 {pct}% {kind}", "ru": "📊 {pct}% {kind}"},
    "stream.kind_day": {"en": "of daily limit", "ru": "дневного лимита"},
    "stream.kind_week": {"en": "of weekly limit", "ru": "недельного лимита"},
    "hotcache.note": {
        "en": "🔥 Warm cache ~{mins} min — reply soon to reuse it (cheaper).",
        "ru": "🔥 Тёплый кэш ~{mins} мин — ответьте скоро, чтобы переиспользовать (дешевле).",
    },
    "hotcache.cold": {
        "en": "❄️ Cache cooled — the next reply rebuilds context from scratch.",
        "ru": "❄️ Кэш остыл — следующий ответ соберёт контекст заново.",
    },
    "usage.set": {
        "en": "Usage display set to <b>{name}</b> — {help}.",
        "ru": "Показ использования: <b>{name}</b> — {help}.",
    },
    "usage.help.off": {
        "en": "do not show subscription usage",
        "ru": "не показывать использование подписки",
    },
    "usage.help.footer": {
        "en": "append a short usage line under each reply",
        "ru": "добавлять короткую строку использования под каждым ответом",
    },
    "usage.help.pinned": {
        "en": "keep a single pinned usage message updated",
        "ru": "обновлять одно закреплённое сообщение об использовании",
    },
    "usage.help.both": {
        "en": "show the footer and the pinned message",
        "ru": "показывать и строку, и закреплённое сообщение",
    },

    # -- /codesplit (owner: each code block as its own message) ------------- #
    "codesplit.owner_only": {
        "en": "Only the owner can change message formatting.",
        "ru": "Менять форматирование сообщений может только владелец.",
    },
    "codesplit.show": {
        "en": "🧩 Each code block as its own message: <b>{state}</b>.\n"
              "<b>on</b> — every fenced code block is sent as a separate message, so "
              "long-press → Copy grabs the whole snippet (handy on mobile, which has "
              "no per-block copy button). <b>off</b> — code stays inline in the reply.\n"
              "Tap to change:",
        "ru": "🧩 Каждый блок кода — отдельным сообщением: <b>{state}</b>.\n"
              "<b>вкл</b> — каждый блок кода отправляется отдельным сообщением, поэтому "
              "долгое нажатие → Копировать берёт весь фрагмент (удобно на телефоне, где "
              "нет кнопки копирования у блока). <b>выкл</b> — код остаётся внутри ответа.\n"
              "Нажмите, чтобы изменить:",
    },
    "codesplit.set": {
        "en": "🧩 Each code block as its own message: <b>{state}</b>.",
        "ru": "🧩 Каждый блок кода — отдельным сообщением: <b>{state}</b>.",
    },
    # -- /workingplate (#175) ---------------------------------------------- #
    "workingplate.show": {
        "en": "⏳ \"Working…\" + ⏹ Stop plate: <b>{state}</b>.\n"
              "<b>on</b> — show the plate (with the Stop button + your limits/context) "
              "a few seconds into a turn. <b>off</b> — never show it (test whether it "
              "makes generation visibly jump). Global; next turn.\nTap to change:",
        "ru": "⏳ Плашка «Working…» + ⏹ Stop: <b>{state}</b>.\n"
              "<b>вкл</b> — показывать плашку (с кнопкой Stop + лимитами/контекстом) "
              "через пару секунд после старта. <b>выкл</b> — не показывать совсем "
              "(проверить, не из-за неё ли прыгает генерация). Глобально; со следующего "
              "хода.\nНажмите, чтобы изменить:",
    },
    "workingplate.set": {
        "en": "⏳ \"Working…\" + ⏹ Stop plate: <b>{state}</b>.",
        "ru": "⏳ Плашка «Working…» + ⏹ Stop: <b>{state}</b>.",
    },

    # -- /stop -------------------------------------------------------------- #
    "stop.error": {
        "en": "Error while stopping: {err}",
        "ru": "Ошибка при остановке: {err}",
    },
    "stop.done": {"en": "Stopped. Queue cleared.", "ru": "Остановлено. Очередь очищена."},
    "stop.nothing": {"en": "Nothing to stop.", "ru": "Нечего останавливать."},

    # -- /whoami ------------------------------------------------------------ #
    "whoami": {
        "en": "Your id: <code>{uid}</code> · username: @{uname}",
        "ru": "Ваш id: <code>{uid}</code> · username: @{uname}",
    },

    # -- /allow /deny /users ------------------------------------------------ #
    "allow.need_arg": {
        "en": "Provide an id or username: <code>/allow 123456</code> or "
              "<code>/allow @user</code>",
        "ru": "Укажите id или username: <code>/allow 123456</code> или "
              "<code>/allow @user</code>",
    },
    "allow.prompt": {
        "en": "Send: <code>&lt;id|@user&gt; [chat|code] [until YYYY-MM-DD]</code> (or /cancel).",
        "ru": "Отправьте: <code>&lt;id|@user&gt; [chat|code] [until ГГГГ-ММ-ДД]</code> (или /cancel).",
    },
    "deny.prompt": {
        "en": "Send the numeric id or @username to revoke (or /cancel).",
        "ru": "Отправьте числовой id или @username для отзыва (или /cancel).",
    },
    "allow.granted": {
        "en": "✅ Granted <code>{val}</code> — level <b>{level}</b>{until}.",
        "ru": "✅ Доступ выдан <code>{val}</code> — уровень <b>{level}</b>{until}.",
    },
    "allow.until": {
        "en": " · until <b>{date}</b>",
        "ru": " · до <b>{date}</b>",
    },
    "allow.bad_date": {
        "en": "Bad date — use <code>until YYYY-MM-DD</code> (or <code>never</code>).",
        "ru": "Неверная дата — используйте <code>until ГГГГ-ММ-ДД</code> (или <code>never</code>).",
    },
    "allow.bad_arg": {
        "en": "Usage: <code>/allow &lt;id|@user&gt; [chat|code] [until YYYY-MM-DD]</code>.",
        "ru": "Использование: <code>/allow &lt;id|@user&gt; [chat|code] [until ГГГГ-ММ-ДД]</code>.",
    },
    "allow.owner": {
        "en": "That's the owner — already has full access.",
        "ru": "Это владелец — у него уже полный доступ.",
    },
    "allow.invalid": {
        "en": "Not a valid id or @username: <code>{val}</code>",
        "ru": "Не похоже на id или @username: <code>{val}</code>",
    },
    "deny.need_arg": {
        "en": "Provide an id or username: <code>/deny 123456</code> or "
              "<code>/deny @user</code>",
        "ru": "Укажите id или username: <code>/deny 123456</code> или "
              "<code>/deny @user</code>",
    },
    "deny.revoked": {
        "en": "Revoked access: <code>{val}</code>.",
        "ru": "Доступ отозван: <code>{val}</code>.",
    },
    "deny.not_found": {
        "en": "Not found in the allowlist: <code>{val}</code>.",
        "ru": "Не найдено в списке доступа: <code>{val}</code>.",
    },
    # -- /level /expire /limit (owner access management; #102/#103/#105) ----- #
    "level.prompt": {
        "en": "Send <code>&lt;id|@user&gt;</code> — I'll then offer chat/code — or "
              "<code>&lt;id|@user&gt; chat|code</code> directly. /cancel to stop.",
        "ru": "Отправьте <code>&lt;id|@user&gt;</code> — затем выберете chat/code — или "
              "сразу <code>&lt;id|@user&gt; chat|code</code>. /cancel — отмена.",
    },
    "level.usage": {
        "en": "Usage: <code>/level &lt;id|@user&gt; chat|code</code>.",
        "ru": "Использование: <code>/level &lt;id|@user&gt; chat|code</code>.",
    },
    "level.set": {
        "en": "✅ <code>{val}</code> is now level <b>{level}</b>.",
        "ru": "✅ <code>{val}</code> теперь уровень <b>{level}</b>.",
    },
    "level.not_found": {
        "en": "No allowlist entry for <code>{val}</code>.",
        "ru": "Нет записи в списке доступа для <code>{val}</code>.",
    },
    "level.pick": {
        "en": "Set the access level for <code>{val}</code>:",
        "ru": "Выберите уровень доступа для <code>{val}</code>:",
    },
    "level.pick_chat": {"en": "💬 chat", "ru": "💬 chat"},
    "level.pick_code": {"en": "🟩 code", "ru": "🟩 code"},
    "expire.prompt": {
        "en": "Send: <code>&lt;id|@user&gt; YYYY-MM-DD</code> (or <code>never</code>; /cancel).",
        "ru": "Отправьте: <code>&lt;id|@user&gt; ГГГГ-ММ-ДД</code> (или <code>never</code>; /cancel).",
    },
    "expire.usage": {
        "en": "Usage: <code>/expire &lt;id|@user&gt; YYYY-MM-DD|never</code>.",
        "ru": "Использование: <code>/expire &lt;id|@user&gt; ГГГГ-ММ-ДД|never</code>.",
    },
    "expire.set": {
        "en": "✅ <code>{val}</code> access expires <b>{date}</b>.",
        "ru": "✅ Доступ <code>{val}</code> истекает <b>{date}</b>.",
    },
    "expire.cleared": {
        "en": "✅ <code>{val}</code> no longer expires.",
        "ru": "✅ Доступ <code>{val}</code> больше не истекает.",
    },
    "expire.bad_date": {
        "en": "Bad date — use <code>YYYY-MM-DD</code> or <code>never</code>.",
        "ru": "Неверная дата — используйте <code>ГГГГ-ММ-ДД</code> или <code>never</code>.",
    },
    "expire.not_found": {
        "en": "No allowlist entry for <code>{val}</code>.",
        "ru": "Нет записи в списке доступа для <code>{val}</code>.",
    },
    "limit.prompt": {
        "en": "Send: <code>&lt;id|@user&gt; &lt;tokens&gt; [day|week]</code> (or <code>off</code>; /cancel).",
        "ru": "Отправьте: <code>&lt;id|@user&gt; &lt;токены&gt; [day|week]</code> (или <code>off</code>; /cancel).",
    },
    "limit.usage": {
        "en": "Usage: <code>/limit &lt;id|@user&gt; &lt;tokens&gt; [day|week] | off</code> (default: day).",
        "ru": "Использование: <code>/limit &lt;id|@user&gt; &lt;токены&gt; [day|week] | off</code> (по умолчанию: day).",
    },
    "limit.set": {
        "en": "✅ <code>{val}</code> — <b>{window}</b> cap set to <b>{n}</b> tokens.",
        "ru": "✅ <code>{val}</code> — лимит на <b>{window}</b>: <b>{n}</b> токенов.",
    },
    "limit.cleared": {
        "en": "✅ Rate limits cleared for <code>{val}</code>.",
        "ru": "✅ Лимиты сняты для <code>{val}</code>.",
    },
    "limit.unlimited": {
        "en": "✅ <code>{val}</code> is now unlimited.",
        "ru": "✅ <code>{val}</code> теперь без лимита.",
    },
    "limit.bad": {
        "en": "Tokens must be a number, or <code>off</code>.",
        "ru": "Токены должны быть числом или <code>off</code>.",
    },
    "limit.not_found": {
        "en": "No allowlist entry for <code>{val}</code>.",
        "ru": "Нет записи в списке доступа для <code>{val}</code>.",
    },

    "users.header": {"en": "<b>Allowed users</b>", "ru": "<b>Разрешённые пользователи</b>"},
    "users.owner_id": {"en": "Owner id: <code>{id}</code>", "ru": "Id владельца: <code>{id}</code>"},
    "users.ids": {"en": "Ids: {ids}", "ru": "Id: {ids}"},
    "users.ids_none": {"en": "Ids: (none)", "ru": "Id: (нет)"},
    "users.usernames": {"en": "Usernames: {names}", "ru": "Username: {names}"},
    "users.usernames_none": {"en": "Usernames: (none)", "ru": "Username: (нет)"},
    "users.footnote": {
        "en": "Numeric ids are authoritative; usernames are a convenience.",
        "ru": "Числовые id — основной критерий; username приведены для удобства.",
    },
    "users.none_entries": {
        "en": "<i>(no other users)</i>",
        "ru": "<i>(других пользователей нет)</i>",
    },
    "users.entry": {
        "en": "• <code>{id}</code>{uname} — <b>{level}</b> · exp: {expiry} · caps: {quota}",
        "ru": "• <code>{id}</code>{uname} — <b>{level}</b> · истекает: {expiry} · лимиты: {quota}",
    },
    "users.pending": {
        "en": "• @{name} — <b>{level}</b> · exp: {expiry} · caps: {quota} <i>(unpinned)</i>",
        "ru": "• @{name} — <b>{level}</b> · истекает: {expiry} · лимиты: {quota} <i>(не привязан)</i>",
    },
    "users.never": {"en": "never", "ru": "никогда"},
    "users.unlimited": {"en": "∞", "ru": "∞"},
    "access.code_denied": {
        "en": "🔒 This is a <b>code</b> session — your access is chat-only. Ask the owner for code access.",
        "ru": "🔒 Это <b>код</b>-сессия — у вас доступ только к чату. Попросите владельца открыть доступ к коду.",
    },
    "access.quota_exceeded": {
        "en": "🔒 Token quota reached (<b>{used}/{grant}</b>). Ask the owner to top up with /limit.",
        "ru": "🔒 Лимит токенов исчерпан (<b>{used}/{grant}</b>). Попросите владельца пополнить через /limit.",
    },

    # -- #120 rolling rate limits + per-user effort/permissions gates ------- #
    "access.rate_day_exceeded": {
        "en": "🔒 Daily usage limit reached (<b>{used}/{cap}</b> units). It frees up as your last 24h of usage ages out.",
        "ru": "🔒 Дневной лимит исчерпан (<b>{used}/{cap}</b> ед.). Освободится по мере устаревания последних 24 часов.",
    },
    "access.rate_week_exceeded": {
        "en": "🔒 Weekly usage limit reached (<b>{used}/{cap}</b> units). It frees up as your last 7 days age out.",
        "ru": "🔒 Недельный лимит исчерпан (<b>{used}/{cap}</b> ед.). Освободится по мере устаревания последних 7 дней.",
    },
    "effort.max_denied": {
        "en": "🔒 The <b>max</b> effort level is restricted (it's costly on the shared subscription). Ask the owner to grant it.",
        "ru": "🔒 Уровень <b>max</b> ограничен (дорого расходует общую подписку). Попросите владельца разрешить его.",
    },
    "perm.chat_na": {
        "en": "Permissions apply to <b>code</b> sessions only — chat's web tools are read-only and auto-approved, so there's nothing to gate here.",
        "ru": "Права применяются только к <b>код</b>-сессиям — веб-инструменты чата только для чтения и одобряются автоматически, гейтить нечего.",
    },

    # -- /users list buttons + the per-user management card (#120) ---------- #
    "users.tap_hint": {
        "en": "<i>Tap a user to manage memory, limits, effort, tools, expiry, and see usage.</i>",
        "ru": "<i>Нажмите на пользователя: память, лимиты, effort, инструменты, срок доступа и статистика.</i>",
    },
    "users.entry_usage": {
        "en": "   ↳ used: day {day} · week {week} · total {total}",
        "ru": "   ↳ расход: день {day} · неделя {week} · всего {total}",
    },
    "users.btn_owner": {"en": "👑 You (owner)", "ru": "👑 Вы (владелец)"},
    "users.btn_add": {"en": "➕ Add user", "ru": "➕ Добавить"},
    "users.btn_stats": {"en": "📊 Statistics", "ru": "📊 Статистика"},
    "users.btn_entry": {"en": "{who} · {level}", "ru": "{who} · {level}"},
    "users.btn_pending": {"en": "@{name} · {level} (unpinned)", "ru": "@{name} · {level} (не привязан)"},
    "usercard.title": {
        "en": "<b>User</b> <code>{who}</code> {kind}",
        "ru": "<b>Пользователь</b> <code>{who}</code> {kind}",
    },
    "usercard.kind_owner": {"en": "(owner)", "ru": "(владелец)"},
    "usercard.kind_pending": {"en": "(unpinned)", "ru": "(не привязан)"},
    "usercard.level": {"en": "Level: <b>{level}</b>", "ru": "Уровень: <b>{level}</b>"},
    "usercard.expiry": {"en": "Access expires: <b>{expiry}</b>", "ru": "Доступ истекает: <b>{expiry}</b>"},
    "usercard.rate": {
        "en": "Limits: day <b>{day}</b> · week <b>{week}</b>",
        "ru": "Лимиты: день <b>{day}</b> · неделя <b>{week}</b>",
    },
    "usercard.memory": {"en": "Global memory: <b>{state}</b>", "ru": "Глобальная память: <b>{state}</b>"},
    "usercard.maxeffort": {"en": "Max effort allowed: <b>{state}</b>", "ru": "Разрешён max effort: <b>{state}</b>"},
    "usercard.tools": {"en": "Tools allowed: <b>{tools}</b>", "ru": "Разрешено инструментов: <b>{tools}</b>"},
    "usercard.cap_all": {"en": "all", "ru": "все"},
    "usercard.usage": {
        "en": "Used: day <b>{day}</b> · week <b>{week}</b> · total <b>{total}</b> ({reqs} req)",
        "ru": "Израсходовано: день <b>{day}</b> · неделя <b>{week}</b> · всего <b>{total}</b> ({reqs} зап.)",
    },
    "usercard.memory_warn": {
        "en": "<i>⚠️ Global memory loads your ~/.claude for this user — not just CLAUDE.md/memory but your <b>settings</b> (permission allow-rules + env). Grant only to fully-trusted users, and keep secrets / allow-rules out of ~/.claude/settings.json.</i>",
        "ru": "<i>⚠️ Глобальная память загружает ваш ~/.claude для этого пользователя — не только CLAUDE.md/память, но и <b>настройки</b> (правила авто-allow + env). Выдавайте только полностью доверенным и не держите секреты / allow-правила в ~/.claude/settings.json.</i>",
    },
    "usercard.owner_note": {
        "en": "<i>The owner is always code and never expires. The limits below are self-imposed for testing — clear them to go back to uncapped.</i>",
        "ru": "<i>Владелец всегда code и не истекает. Лимиты ниже — самоограничения для теста; сбросьте их, чтобы снова стать без лимитов.</i>",
    },
    "usercard.not_found": {"en": "User not found.", "ru": "Пользователь не найден."},
    "usercard.btn_level": {"en": "Level: {level} → {next}", "ru": "Уровень: {level} → {next}"},
    # #154: 🗄 for memory/context (🧠 is reserved for MODEL across all surfaces).
    "usercard.btn_memory": {"en": "🗄 Memory: {state}", "ru": "🗄 Память: {state}"},
    "usercard.btn_maxeffort": {"en": "⚡ Max effort: {state}", "ru": "⚡ Max effort: {state}"},
    "usercard.btn_tools": {"en": "🧰 Tools: {val}", "ru": "🧰 Инструменты: {val}"},
    # #151: per-user access EXCEPTIONS (menu.md §3.4/§4).
    "usercard.btn_access": {"en": "🔑 Access", "ru": "🔑 Доступ"},
    "usercard.access_header": {
        "en": "🔑 <b>Access for</b> <code>{who}</code>\nPer-option access for this user "
              "— an EXCEPTION overrides the global base. Tap an option to change it.",
        "ru": "🔑 <b>Доступ для</b> <code>{who}</code>\nДоступ к опциям для этого "
              "пользователя — ИСКЛЮЧЕНИЕ переопределяет базу. Нажмите опцию, чтобы изменить.",
    },
    "usercard.access_base": {"en": "base: {val}", "ru": "база: {val}"},
    "usercard.access_base_opt": {"en": "Base (inherit)", "ru": "База (наследовать)"},
    "usercard.access_opt_title": {
        "en": "🔑 <b>{name}</b>\nAccess for this user (Base = follow the global base).",
        "ru": "🔑 <b>{name}</b>\nДоступ для пользователя (База = по глобальной базе).",
    },
    "usercard.btn_name": {"en": "✏️ Friendly name…", "ru": "✏️ Имя…"},
    "usercard.btn_expiry": {"en": "⏳ Set expiry…", "ru": "⏳ Срок доступа…"},
    "usercard.btn_day": {"en": "📊 Day limit…", "ru": "📊 Лимит/день…"},
    "usercard.btn_week": {"en": "📅 Week limit…", "ru": "📅 Лимит/неделя…"},
    "usercard.btn_idle": {"en": "⏳ Idle: {val}", "ru": "⏳ Простой: {val}"},
    "usercard.idle_default": {"en": "default", "ru": "по умолч."},
    "usercard.btn_clear_limits": {"en": "♾ Clear limits", "ru": "♾ Снять лимиты"},
    "usercard.btn_remove": {"en": "🗑 Remove access", "ru": "🗑 Убрать доступ"},
    "usercard.btn_back": {"en": "◂ Users", "ru": "◂ Пользователи"},
    "usercard.tools_header": {
        "en": "🧰 <b>Tools for</b> <code>{who}</code>\nTap to allow / deny each. Applies to all their sessions.",
        "ru": "🧰 <b>Инструменты для</b> <code>{who}</code>\nНажмите, чтобы разрешить / запретить. Действует на все их сессии.",
    },
    "usercard.btn_confirm_remove": {"en": "🗑 Yes, remove", "ru": "🗑 Да, убрать"},
    "usercard.confirm_remove": {
        "en": "Remove access for <code>{who}</code>?",
        "ru": "Убрать доступ для <code>{who}</code>?",
    },
    "usercard.prompt_name": {
        "en": "Send a friendly name for this user (or <code>-</code> to clear; /cancel).",
        "ru": "Отправьте имя для этого пользователя (или <code>-</code> чтобы убрать; /cancel).",
    },
    "usercard.prompt_expiry": {
        "en": "Send an expiry date <code>YYYY-MM-DD</code> (or <code>never</code>; /cancel).",
        "ru": "Отправьте дату окончания <code>ГГГГ-ММ-ДД</code> (или <code>never</code>; /cancel).",
    },
    "usercard.prompt_day": {
        "en": "Send the DAILY token cap (e.g. <code>500k</code>, or <code>off</code>; /cancel).",
        "ru": "Отправьте ДНЕВНОЙ лимит токенов (напр. <code>500k</code>, или <code>off</code>; /cancel).",
    },
    "usercard.prompt_week": {
        "en": "Send the WEEKLY token cap (e.g. <code>2m</code>, or <code>off</code>; /cancel).",
        "ru": "Отправьте НЕДЕЛЬНЫЙ лимит токенов (напр. <code>2m</code>, или <code>off</code>; /cancel).",
    },
    "usercard.prompt_idle": {
        "en": "Send the idle-TTL in <b>minutes</b> (e.g. <code>6</code>), <code>off</code> for ∞ (never reap), or <code>default</code> for the server default. /cancel to abort.",
        "ru": "Отправьте таймаут простоя в <b>минутах</b> (напр. <code>6</code>), <code>off</code> для ∞ (не выгружать), или <code>default</code> для значения по умолчанию. /cancel — отмена.",
    },
    "usercard.sessions": {"en": "🔢 Session limit: <b>{val}</b>", "ru": "🔢 Лимит сессий: <b>{val}</b>"},
    "usercard.sessions_default": {"en": "default", "ru": "по умолч."},
    "usercard.btn_sessions": {"en": "🔢 Sessions: {val}", "ru": "🔢 Сессии: {val}"},
    "usercard.prompt_sessions": {
        "en": "Send the session limit — a number (e.g. <code>10</code>), <code>off</code> for "
              "unlimited, or <code>default</code> to inherit the global. /cancel to abort.",
        "ru": "Отправьте лимит сессий — число (напр. <code>10</code>), <code>off</code> для "
              "безлимита, или <code>default</code> чтобы наследовать глобальный. /cancel — отмена.",
    },
    "whoami.usage": {
        "en": "Usage — day <b>{day}</b> · week <b>{week}</b> · total <b>{total}</b>",
        "ru": "Расход — день <b>{day}</b> · неделя <b>{week}</b> · всего <b>{total}</b>",
    },
    "whoami.caps": {"en": "Limits: <b>{caps}</b>", "ru": "Лимиты: <b>{caps}</b>"},

    # -- /status ------------------------------------------------------------ #
    "status.header": {
        "en": "{glyph} <b>{name}</b> · <b>{mode}</b> session · <code>{sid}</code>",
        "ru": "{glyph} <b>{name}</b> · сессия <b>{mode}</b> · <code>{sid}</code>",
    },
    "status.model": {"en": "Model: <code>{model}</code>", "ru": "Модель: <code>{model}</code>"},
    "status.directory": {
        "en": "📂 <code>{cwd} $</code>",
        "ru": "📂 <code>{cwd} $</code>",
    },
    "status.permissions": {"en": "Permissions: <b>{perm}</b>", "ru": "Права: <b>{perm}</b>"},
    "status.usage_display": {
        "en": "Usage display: <b>{usage}</b>",
        "ru": "Показ использования: <b>{usage}</b>",
    },
    "status.streaming": {"en": "Streaming: <b>{state}</b>", "ru": "Стриминг: <b>{state}</b>"},
    "status.big_memory": {"en": "Big memory: <b>{state}</b>", "ru": "Большая память: <b>{state}</b>"},
    "status.busy": {
        "en": "Busy: {busy}; queued: {queued}",
        "ru": "Занят: {busy}; в очереди: {queued}",
    },
    # #170: native-checklist labels (the checkbox itself shows on/off).
    "status.chk_bigmem": {"en": "Big memory (1M context)", "ru": "Большая память (1M контекст)"},
    "status.chk_busy": {"en": "Busy ({queued} queued)", "ru": "Занят (в очереди: {queued})"},
    "status.cache": {
        "en": "Cache window (5 min): ~{secs}s left",
        "ru": "Окно кэша (5 мин): осталось ~{secs}с",
    },
    "status.limits_header": {
        "en": "<b>Subscription limits</b>",
        "ru": "<b>Лимиты подписки</b>",
    },
    "status.trend_header": {
        "en": "📈 Limit trend (recent utilization %, last ~hour)",
        "ru": "📈 Тренд лимитов (недавняя загрузка %, ~час)",
    },
    "status.totals_header": {
        "en": "Usage (session lifetime)",
        "ru": "Использование (за всё время сессии)",
    },
    "status.requests": {"en": "Requests: {n}", "ru": "Запросов: {n}"},
    "status.tokens": {
        "en": "Tokens: {inp} in · {out} out",
        "ru": "Токены: {inp} вход · {out} выход",
    },
    "status.cache_tokens": {
        "en": "Cache: {read} read · {created} created",
        "ru": "Кэш: {read} чтение · {created} создание",
    },
    "status.cost": {"en": "Estimated cost: ${cost}", "ru": "Примерная стоимость: ${cost}"},
    # /status rate-snapshot fallback labels (used when the multi-window block is empty).
    "status.rate_type": {"en": "type: {val}", "ru": "тип: {val}"},
    "status.rate_status": {"en": "status: {val}", "ru": "статус: {val}"},
    "status.rate_util": {"en": "utilization: {val}%", "ru": "загрузка: {val}%"},
    "status.rate_resets": {"en": "resets: {val}", "ru": "сброс: {val}"},

    # -- /context ----------------------------------------------------------- #
    "context.read_error": {
        "en": "Could not read context usage: <code>{err}</code>",
        "ru": "Не удалось прочитать использование контекста: <code>{err}</code>",
    },
    "context.no_session": {
        "en": "No active session yet — send a message first.",
        "ru": "Активной сессии ещё нет — сначала отправьте сообщение.",
    },
    "context.header": {"en": "<b>Context window</b>", "ru": "<b>Окно контекста</b>"},
    "context.used": {
        "en": "Used: <code>{n}</code> tokens",
        "ru": "Использовано: <code>{n}</code> токенов",
    },
    "context.total": {
        "en": "Total: <code>{n}</code> tokens",
        "ru": "Всего: <code>{n}</code> токенов",
    },
    "context.usage": {"en": "Usage: <code>{pct}%</code>", "ru": "Заполнено: <code>{pct}%</code>"},

    # -- /recap, /history --------------------------------------------------- #
    # Model-facing instruction for the AI /recap (one-line session recap). Localized
    # so the recap comes back in the user's UI language (the model mirrors it).
    "recap.prompt": {
        "en": "Recap our conversation so far in one short sentence.",
        "ru": "Кратко изложи нашу беседу одним коротким предложением.",
    },
    "recap.empty": {
        "en": "No conversation logged yet in this session.",
        "ru": "В этой сессии ещё нет записанного разговора.",
    },
    "recap.empty_has_context": {
        "en": "No transcript is saved for this session yet — earlier turns predate "
              "transcript logging, so /last and /history can't replay them, but the "
              "model may still recall them from its own context. New messages are saved "
              "from now on.",
        "ru": "Для этой сессии ещё нет сохранённой расшифровки — ранние сообщения были "
              "до ведения журнала, поэтому /last и /history не могут их показать, но "
              "модель всё ещё может помнить их из своего контекста. Новые сообщения "
              "сохраняются с этого момента.",
    },
    "recap.header": {
        "en": "<b>Last exchange</b>",
        "ru": "<b>Последний обмен</b>",
    },
    "recap.you": {"en": "<b>You:</b>", "ru": "<b>Вы:</b>"},
    "recap.claude": {"en": "<b>Claude:</b>", "ru": "<b>Claude:</b>"},
    "recap.footnote": {
        "en": "<i>/history exports the full transcript.</i>",
        "ru": "<i>/history выгружает полную расшифровку.</i>",
    },
    "history.title": {"en": "Transcript — {name}", "ru": "Расшифровка — {name}"},
    "history.you": {"en": "You", "ru": "Вы"},
    "history.claude": {"en": "Claude", "ru": "Claude"},
    "history.export_error": {
        "en": "Could not export the transcript: {err}",
        "ru": "Не удалось выгрузить расшифровку: {err}",
    },

    # -- /stream ------------------------------------------------------------ #
    "stream.show": {
        "en": "Live streaming: <b>{current}</b>.",
        "ru": "Живой стриминг: <b>{current}</b>.",
    },
    "stream.usage": {
        "en": "Usage: <code>/stream on</code> or <code>/stream off</code>.",
        "ru": "Использование: <code>/stream on</code> или <code>/stream off</code>.",
    },
    "stream.change_error": {
        "en": "Could not change streaming: <code>{err}</code>",
        "ru": "Не удалось изменить стриминг: <code>{err}</code>",
    },
    "stream.set": {
        "en": "Live streaming: <b>{state}</b>. When off, replies arrive as a "
              "single message.",
        "ru": "Живой стриминг: <b>{state}</b>. Когда выкл, ответы приходят одним "
              "сообщением.",
    },

    # -- /close (frozen group path) + topic errors -------------------------- #
    "topic.not_a_topic_rename": {
        "en": "This is not a forum topic; nothing to rename.",
        "ru": "Это не тема форума; переименовывать нечего.",
    },
    "topic.not_a_topic_close": {
        "en": "This is not a forum topic; nothing to close.",
        "ru": "Это не тема форума; закрывать нечего.",
    },
    "topic.closed": {"en": "Topic closed.", "ru": "Тема закрыта."},
    "topic.renamed": {
        "en": "Topic renamed to <b>{name}</b>.",
        "ru": "Тема переименована в <b>{name}</b>.",
    },
    "topic.create_error": {
        "en": "Could not create the topic. Make sure Topics are enabled in the "
              "group and the bot has the manage-topics permission "
              "(can_manage_topics).\nDetails: {err}",
        "ru": "Не удалось создать тему. Убедитесь, что Темы включены в группе и у "
              "бота есть право управления темами (can_manage_topics).\n"
              "Подробности: {err}",
    },
    "topic.created": {
        "en": "Created a new topic: <b>{name}</b>. It becomes a separate session "
              "on the first message sent in it.",
        "ru": "Создана новая тема: <b>{name}</b>. Она становится отдельной сессией "
              "при первом отправленном в неё сообщении.",
    },
    "topic.rename_error": {
        "en": "Could not rename the topic. The bot needs the Manage Topics "
              "permission.\nDetails: {err}",
        "ru": "Не удалось переименовать тему. Боту нужно право Manage Topics.\n"
              "Подробности: {err}",
    },
    "topic.close_error": {
        "en": "Could not close the topic. The bot needs the Manage Topics "
              "permission.\nDetails: {err}",
        "ru": "Не удалось закрыть тему. Боту нужно право Manage Topics.\n"
              "Подробности: {err}",
    },

    # -- /queue ------------------------------------------------------------- #
    "queue.empty": {"en": "Queue is empty.", "ru": "Очередь пуста."},
    "queue.header": {"en": "<b>Queued prompts:</b> {n}", "ru": "<b>Запросов в очереди:</b> {n}"},
    "queue.cancel_btn": {"en": "✖ Cancel {i}", "ru": "✖ Отменить {i}"},
    "queue.cleared_toast": {"en": "Cleared {n}.", "ru": "Очищено: {n}."},
    "queue.cancelled_toast": {"en": "Cancelled.", "ru": "Отменено."},
    "queue.already_running": {"en": "Already running.", "ru": "Уже выполняется."},
    "queue.cleared": {
        "en": "Cleared {n} queued message(s). The current run keeps going — tap "
              "the Stop button on the live reply to halt it.",
        "ru": "Очищено сообщений в очереди: {n}. Текущий запуск продолжается — "
              "нажмите кнопку Стоп под идущим ответом, чтобы остановить его.",
    },
    "queue.clear_error": {
        "en": "Could not clear the queue: <code>{err}</code>",
        "ru": "Не удалось очистить очередь: <code>{err}</code>",
    },

    # -- ⏹ stop button / control message ------------------------------------ #
    "stopbtn.stopping": {"en": "Stopping…", "ru": "Останавливаю…"},
    "stopbtn.nothing": {"en": "Nothing is running.", "ru": "Ничего не выполняется."},
    "stream.working": {"en": "⏳ <i>Working…</i>", "ru": "⏳ <i>Работаю…</i>"},
    "stream.too_long": {
        "en": "📄 Response too long — sent as a file.",
        "ru": "📄 Ответ слишком длинный — отправлен файлом.",
    },

    # -- /retry ------------------------------------------------------------- #
    "retry.error": {
        "en": "Could not retry: <code>{err}</code>",
        "ru": "Не удалось повторить: <code>{err}</code>",
    },
    "retry.ok": {"en": "Re-running the last prompt.", "ru": "Повторяю последний запрос."},
    "retry.nothing": {"en": "Nothing to retry yet.", "ru": "Пока нечего повторять."},

    # -- text / attachments ------------------------------------------------- #
    "text.process_error": {
        "en": "Could not process the message: {err}",
        "ru": "Не удалось обработать сообщение: {err}",
    },
    "attach.process_error": {
        "en": "Could not process the attachment: {err}",
        "ru": "Не удалось обработать вложение: {err}",
    },
    "attach.too_large": {
        "en": "File is too large (max {mb} MB). Send a smaller one.",
        "ru": "Файл слишком большой (макс. {mb} МБ). Отправьте файл поменьше.",
    },
    "attach.download_error": {
        "en": "Could not download the file: {err}",
        "ru": "Не удалось скачать файл: {err}",
    },
    # #187: outbox file send-back notices.
    "outbox.too_big": {
        "en": "📎 Too large to send to chat: {names}. Use /export to download the workdir.",
        "ru": "📎 Слишком большие для отправки в чат: {names}. Используйте /export, чтобы скачать рабочую папку.",
    },
    "outbox.more": {
        "en": "📎 {n} more file(s) staged in outbox/ — they'll be sent after the next turn.",
        "ru": "📎 Ещё {n} файл(ов) в outbox/ — отправлю после следующего хода.",
    },
    "attach.read_error": {
        "en": "Could not read the file.",
        "ru": "Не удалось прочитать файл.",
    },
    "attach.bad_image": {
        "en": "Unsupported image type. Send a JPEG, PNG, GIF, or WebP (HEIC and "
              "similar are not supported).",
        "ru": "Неподдерживаемый тип изображения. Отправьте JPEG, PNG, GIF или WebP "
              "(HEIC и подобные не поддерживаются).",
    },
    "attach.bad_file": {
        "en": "Unsupported file type. Send an image, a PDF, or a UTF-8 text/code "
              "file.",
        "ru": "Неподдерживаемый тип файла. Отправьте изображение, PDF или "
              "текстовый/кодовый файл в UTF-8.",
    },
    "attach.truncated": {"en": "[file truncated]", "ru": "[файл обрезан]"},
    "attach.default_image_prompt": {
        "en": "Describe this image.",
        "ru": "Опиши это изображение.",
    },
    "attach.default_doc_prompt": {
        "en": "Here is a document. Summarize the key points.",
        "ru": "Вот документ. Кратко изложи ключевые моменты.",
    },

    # -- permission gate (permissions.py) ----------------------------------- #
    "permgate.allow_btn": {"en": "✅ Allow", "ru": "✅ Разрешить"},
    "permgate.deny_btn": {"en": "⛔ Deny", "ru": "⛔ Запретить"},
    "permgate.request": {
        "en": "🔐 Permission request: <b>{tool}</b>",
        "ru": "🔐 Запрос разрешения: <b>{tool}</b>",
    },
    "permgate.run_q": {"en": "Run this tool?", "ru": "Запустить этот инструмент?"},
    "permgate.timed_out": {
        "en": "⌛ Approval timed out — denied.",
        "ru": "⌛ Время на подтверждение истекло — отклонено.",
    },
    "permgate.cancelled": {
        "en": "⏹ Request cancelled (stopped).",
        "ru": "⏹ Запрос отменён (остановлено).",
    },
    "permgate.invalid": {"en": "Invalid request.", "ru": "Некорректный запрос."},
    "permgate.expired": {
        "en": "Request expired or already handled.",
        "ru": "Запрос истёк или уже обработан.",
    },
    "permgate.allowed_msg": {"en": "✅ Allowed.", "ru": "✅ Разрешено."},
    "permgate.denied_msg": {"en": "⛔ Denied.", "ru": "⛔ Запрещено."},
    "permgate.allowed_toast": {"en": "Allowed", "ru": "Разрешено"},
    "permgate.denied_toast": {"en": "Denied", "ru": "Запрещено"},
    "permgate.owner_only": {
        "en": "Only the owner can approve tools.",
        "ru": "Одобрять инструменты может только владелец.",
    },
    "permgate.processing_error": {"en": "Processing error.", "ru": "Ошибка обработки."},

    # -- session manager notices (sessions.py) ------------------------------ #
    "session.not_initialized": {
        "en": "⚠️ Session not initialized.",
        "ru": "⚠️ Сессия не инициализирована.",
    },
    "session.unknown_error": {"en": "Unknown error.", "ru": "Неизвестная ошибка."},
    "session.internal_error": {
        "en": "⚠️ Internal error: {exc}",
        "ru": "⚠️ Внутренняя ошибка: {exc}",
    },
    "busy.queued": {
        "en": "⏳ Server busy — your turn is queued and will run as soon as a slot frees up.",
        "ru": "⏳ Сервер занят — ваш ход в очереди и начнётся, как только освободится слот.",
    },

    # -- engine error events (engine.py emits a stable error_key) ------------ #
    "err.authentication_failed": {
        "en": "Authentication error. Check your subscription login "
              "(claude setup-token) and that ANTHROPIC_API_KEY is unset.",
        "ru": "Ошибка аутентификации. Проверьте вход в подписку "
              "(claude setup-token) и что ANTHROPIC_API_KEY не задан.",
    },
    "err.billing_error": {
        "en": "Billing error. Check your subscription status.",
        "ru": "Ошибка оплаты. Проверьте статус подписки.",
    },
    "err.rate_limit": {
        "en": "Subscription limit reached — the usage window is exhausted. "
              "Please try again after it resets.",
        "ru": "Достигнут лимит подписки — окно использования исчерпано. "
              "Попробуйте снова после его сброса.",
    },
    "err.invalid_request": {
        "en": "Invalid request to the model.",
        "ru": "Некорректный запрос к модели.",
    },
    "err.server_error": {
        "en": "Server-side error. Please try again.",
        "ru": "Ошибка на стороне сервера. Попробуйте ещё раз.",
    },
    "err.unknown_model": {"en": "Unknown model error.", "ru": "Неизвестная ошибка модели."},
    "err.model_error": {"en": "Model error: {detail}", "ru": "Ошибка модели: {detail}"},
    "err.start_failed": {
        "en": "Failed to start session: {detail}",
        "ru": "Не удалось запустить сессию: {detail}",
    },
    "err.exec_error": {
        "en": "Execution error: {detail}",
        "ru": "Ошибка выполнения: {detail}",
    },

    # -- usage windows (usage.py) ------------------------------------------- #
    "usage.status.ok": {"en": "OK", "ru": "OK"},
    "usage.status.high": {"en": "⚠ high", "ru": "⚠ высокое"},
    "usage.status.limited": {"en": "⛔ limited", "ru": "⛔ лимит"},
    # #135/#137: neutral marker for a present-but-unrecognized window status — we no
    # longer assert "OK" for a state we don't actually understand.
    "usage.status.unknown": {"en": "—", "ru": "—"},
    "usage.left": {"en": "{pct}% left", "ru": "осталось {pct}%"},
    "usage.resets": {"en": "resets {when}", "ru": "сброс через {when}"},
    "usage.reset_hm": {"en": "{h}h{m}m", "ru": "{h}ч{m}м"},
    "usage.reset_m": {"en": "{m}m", "ru": "{m}м"},
    "usage.reset_lt1m": {"en": "<1m", "ru": "<1м"},
    "usage.pinned_header": {
        "en": "📊 Subscription usage",
        "ru": "📊 Использование подписки",
    },
    # Window labels (model names opus/sonnet stay English; only "overage" differs).
    "usage.label.overage": {"en": "overage", "ru": "перерасход"},

    # -- command-menu descriptions (setMyCommands) -------------------------- #
    # #139: the command-menu descriptions are now the SINGLE SOURCE OF TRUTH in
    # commands.py (the COMMANDS registry, Cmd.label["en"/"ru"]). The cmd.* rows
    # below are SUPERSEDED for the menu and commented out (kept for audit/revert)
    # so a command name + one-liner is defined exactly once per language. To edit
    # a menu description, edit the matching Cmd.label in commands.py.
    #
    # was — replaced for #139 (now in commands.py COMMANDS registry). Note:
    # cmd.stop / cmd.stream were stale (those handlers are commented out) and are
    # intentionally NOT carried over; cmd.cwd / cmd.dirs / cmd.reset had no live
    # handler and were dead — also dropped.
    # "cmd.new": {"en": "➕ New chat session", "ru": "➕ Новая сессия (чат)"},
    # "cmd.code": {"en": "🟩 Upgrade this session to code", "ru": "🟩 Повысить сессию до кода"},
    # "cmd.chat": {"en": "💬 Downgrade this session to chat", "ru": "💬 Понизить сессию до чата"},
    # "cmd.newchat": {"en": "💬 New chat session", "ru": "💬 Новая чат-сессия"},
    # "cmd.newcode": {"en": "🟩 New code session", "ru": "🟩 Новая код-сессия"},
    # "cmd.sessions": {
    #     "en": "Browse / switch / delete sessions",
    #     "ru": "Обзор / переключение / удаление сессий",
    # },
    # "cmd.rename": {"en": "Rename the current session", "ru": "Переименовать текущую сессию"},
    # "cmd.status": {"en": "Current session info", "ru": "Сведения о текущей сессии"},
    # "cmd.stop": {"en": "Stop the current reply", "ru": "Остановить текущий ответ"},
    # "cmd.retry": {"en": "Re-run the last prompt", "ru": "Повторить последний запрос"},
    # "cmd.clear": {"en": "Clear the session context", "ru": "Очистить контекст сессии"},
    # "cmd.reset": {"en": "Clear the session context (alias of /clear)", "ru": "Очистить контекст (синоним /clear)"},
    # "cmd.model": {
    #     "en": "Switch model: opus | sonnet | haiku",
    #     "ru": "Сменить модель: opus | sonnet | haiku",
    # },
    # "cmd.effort": {"en": "Reasoning depth: low … max", "ru": "Глубина рассуждений: low … max"},
    # "cmd.fork": {
    #     "en": "Branch this session into a new one",
    #     "ru": "Ответвить эту сессию в новую",
    # },
    # "cmd.memory": {
    #     "en": "1M context window (chat): on | off",
    #     "ru": "Окно контекста 1M (чат): on | off",
    # },
    # "cmd.permissions": {
    #     "en": "Code tool policy: ask | auto-edits | plan",
    #     "ru": "Политика инструментов кода: ask | auto-edits | plan",
    # },
    # "cmd.cwd": {"en": "Working directory (code sessions)", "ru": "Рабочая папка (код-сессии)"},
    # "cmd.dirs": {"en": "Extra code directories", "ru": "Доп. папки для кода"},
    # "cmd.files": {"en": "Browse the working-dir tree (code)", "ru": "Дерево рабочей папки (код)"},
    # "cmd.export": {"en": "Export working-dir files as .zip (code)", "ru": "Экспорт файлов рабочей папки (.zip, код)"},
    # "cmd.sandbox": {"en": "Toggle this code session's sandbox (owner)", "ru": "Песочница код-сессии вкл/выкл (владелец)"},
    # "cmd.maxturns": {"en": "Cap agentic turns (code)", "ru": "Лимит агентных ходов (код)"},
    # "cmd.recap": {"en": "Show the last exchange", "ru": "Показать последний обмен"},
    # "cmd.history": {
    #     "en": "Export this session's transcript",
    #     "ru": "Выгрузить расшифровку этой сессии",
    # },
    # "cmd.usage": {"en": "Subscription-usage display", "ru": "Показ использования подписки"},
    # "cmd.context": {"en": "Context-window usage", "ru": "Использование окна контекста"},
    # "cmd.queue": {"en": "Show the pending-prompt queue", "ru": "Показать очередь запросов"},
    # "cmd.clearqueue": {"en": "Clear the pending queue", "ru": "Очистить очередь"},
    # "cmd.stream": {"en": "Live streaming: on | off", "ru": "Живой стриминг: on | off"},
    # "cmd.settings": {"en": "Open the settings menu", "ru": "Открыть меню настроек"},
    # "cmd.tools": {"en": "Configure this session's tools", "ru": "Настроить инструменты сессии"},
    # "cmd.language": {"en": "Choose the interface language", "ru": "Выбрать язык интерфейса"},
    # "cmd.help": {"en": "Show help", "ru": "Показать справку"},
    # "cmd.whoami": {"en": "Show your id and username", "ru": "Показать ваш id и username"},
    # "cmd.auto": {
    #     "en": "Run code tools without asking (owner)",
    #     "ru": "Запускать инструменты кода без вопросов (владелец)",
    # },
    # "cmd.allow": {"en": "Allow a user (owner)", "ru": "Разрешить пользователя (владелец)"},
    # "cmd.deny": {"en": "Remove a user (owner)", "ru": "Удалить пользователя (владелец)"},
    # "cmd.users": {"en": "List allowed users (owner)", "ru": "Список пользователей (владелец)"},
    # "cmd.level": {"en": "Set a user's access level (owner)", "ru": "Уровень доступа (владелец)"},
    # "cmd.expire": {"en": "Set a user's access expiry (owner)", "ru": "Срок доступа (владелец)"},
    # "cmd.limit": {"en": "Top up a user's token grant (owner)", "ru": "Пополнить лимит токенов (владелец)"},
}


def t(key: str, lang: str = DEFAULT_LANG, /, **kwargs) -> str:
    """Look up `key` in the requested locale and format it with `kwargs`.

    `lang` is positional-only so a catalog placeholder named ``{lang}`` (or any
    other t-parameter name) can still be supplied via kwargs without colliding.

    Falls back to the English column when the locale lacks the key, and to the
    raw key when the key itself is unknown — so a missing translation degrades
    gracefully (visible, never a crash). HTML tags and placeholders are part of
    the stored value and must match across columns.
    """
    row = CATALOG.get(key)
    if row is None:
        text = key
    else:
        text = row.get(lang) or row.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# --------------------------------------------------------------------------- #
# Small display helpers (so on/off, yes/no and the mode word localize once).
# --------------------------------------------------------------------------- #
def onoff(value: bool, lang: str = DEFAULT_LANG) -> str:
    """Localized 'on'/'off' for a boolean."""
    return t("common.on", lang) if value else t("common.off", lang)


def yesno(value: bool, lang: str = DEFAULT_LANG) -> str:
    """Localized 'yes'/'no' for a boolean."""
    return t("common.yes", lang) if value else t("common.no", lang)


def mode_word(mode: str, lang: str = DEFAULT_LANG) -> str:
    """Localized session-type word for display ('chat'/'code')."""
    return t("mode.word_code" if mode == "code" else "mode.word_chat", lang)


def lang_name(lang: str) -> str:
    """Display name of a locale (its own language), or the code if unknown."""
    return LANGUAGES.get(lang, lang)
