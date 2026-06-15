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
    "help.text": {
        "en": (
            "<b>Your personal Claude &amp; Claude Code in Telegram</b>\n"
            "\n"
            "The bot keeps <b>named sessions</b> you switch between — each fully "
            "isolated (histories never cross). A session is either <b>💬 chat</b> "
            "(a plain conversation) or <b>🟩 code</b> (a Claude Code agent with "
            "tools and its own working directory). The type is fixed when you "
            "create the session.\n"
            "\n"
            "Just send a message to talk in the current session; messages sent "
            "while a reply runs are queued and run next in the SAME session "
            "(context + prompt cache preserved). Send a <b>photo</b>, <b>PDF</b>, "
            "or <b>text/code file</b> and the caption becomes the prompt.\n"
            "\n"
            "<b>Sessions:</b>\n"
            "/newchat &lt;name&gt; — start a 💬 chat session · /newcode &lt;name&gt; — "
            "start a 🟩 code session (type is fixed for the session's life)\n"
            "/sessions — browse / search / switch; tap 🗑 to delete one\n"
            "/rename &lt;name&gt; — rename the current session\n"
            "/reset — clear the current session · /stop — stop the current reply\n"
            "/status — current session info · /context — context-window usage\n"
            "\n"
            "<b>Settings:</b>\n"
            "/settings — tap-to-change menu (model, permissions, memory, usage, …)\n"
            "/language — choose the bot's interface language\n"
            "/model &lt;opus|sonnet|haiku&gt; — model for this session\n"
            "/memory &lt;on|off&gt; — 1M context window for a chat session\n"
            "/usage &lt;off|footer|pinned|both&gt; — how subscription usage is shown\n"
            "\n"
            "<b>Code mode:</b>\n"
            "/auto &lt;on|off&gt; — run tools without asking (owner) · /permissions — policy\n"
            "/files — browse the session's working-directory tree (read-only)\n"
            "\n"
            "<b>Run control:</b>\n"
            "/queue · /clearqueue — the pending-prompt queue · /retry — re-run last prompt\n"
            "\n"
            "<b>Owner:</b> /allow, /deny, /users — manage access · /whoami — your id\n"
            "\n"
            "With <code>/auto on</code> code-mode tools run without asking; "
            "otherwise dangerous tools (Bash, Write, Edit) ask for an inline "
            "Allow/Deny tap."
        ),
        "ru": (
            "<b>Ваш личный Claude и Claude Code в Telegram</b>\n"
            "\n"
            "Бот хранит <b>именованные сессии</b>, между которыми вы "
            "переключаетесь — каждая полностью изолирована (истории не "
            "пересекаются). Сессия бывает либо <b>💬 чат</b> (обычный разговор), "
            "либо <b>🟩 код</b> (агент Claude Code с инструментами и собственной "
            "рабочей папкой). Тип задаётся при создании сессии и не меняется.\n"
            "\n"
            "Просто отправьте сообщение, чтобы говорить в текущей сессии; "
            "сообщения, отправленные пока идёт ответ, ставятся в очередь и "
            "выполняются следующими в ТОЙ ЖЕ сессии (контекст и кэш промпта "
            "сохраняются). Отправьте <b>фото</b>, <b>PDF</b> или "
            "<b>текстовый/кодовый файл</b> — подпись станет запросом.\n"
            "\n"
            "<b>Сессии:</b>\n"
            "/newchat &lt;имя&gt; — создать 💬 чат-сессию · /newcode &lt;имя&gt; — "
            "создать 🟩 код-сессию (тип фиксируется на всё время сессии)\n"
            "/sessions — обзор / поиск / переключение; 🗑 чтобы удалить\n"
            "/rename &lt;имя&gt; — переименовать текущую сессию\n"
            "/reset — очистить текущую сессию · /stop — остановить текущий ответ\n"
            "/status — сведения о сессии · /context — использование окна контекста\n"
            "\n"
            "<b>Настройки:</b>\n"
            "/settings — меню изменений в одно касание (модель, права, память, "
            "использование, …)\n"
            "/language — выбрать язык интерфейса бота\n"
            "/model &lt;opus|sonnet|haiku&gt; — модель для этой сессии\n"
            "/memory &lt;on|off&gt; — окно контекста 1M для чат-сессии\n"
            "/usage &lt;off|footer|pinned|both&gt; — как показывать использование "
            "подписки\n"
            "\n"
            "<b>Режим кода:</b>\n"
            "/auto &lt;on|off&gt; — запускать инструменты без вопросов (владелец) · "
            "/permissions — политика\n"
            "/files — дерево рабочей папки сессии (только чтение)\n"
            "\n"
            "<b>Управление запуском:</b>\n"
            "/queue · /clearqueue — очередь ожидающих запросов · /retry — "
            "повторить последний запрос\n"
            "\n"
            "<b>Владелец:</b> /allow, /deny, /users — управление доступом · "
            "/whoami — ваш id\n"
            "\n"
            "При <code>/auto on</code> инструменты режима кода запускаются без "
            "вопросов; иначе опасные инструменты (Bash, Write, Edit) спрашивают "
            "подтверждение через кнопки Разрешить/Запретить."
        ),
    },

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
    "settings.back_to": {"en": "◂ Settings", "ru": "◂ Настройки"},
    "settings.saved": {"en": "✓ Saved", "ru": "✓ Сохранено"},
    "settings.row_perm": {"en": "🔐 Permissions: {val} ▸", "ru": "🔐 Права: {val} ▸"},
    "settings.row_usage": {"en": "📊 Usage: {val} ▸", "ru": "📊 Использование: {val} ▸"},
    "settings.row_streaming": {"en": "Streaming: {val}", "ru": "Стриминг: {val}"},
    "settings.row_memory": {"en": "Big memory: {val}", "ru": "Большая память: {val}"},

    # -- session create / switch / rename / delete -------------------------- #
    "session.created": {
        "en": "Created {glyph} <b>{name}</b> and switched to it.\n{tagline}\n"
              "Send a message to start · /rename to rename · /sessions to switch.",
        "ru": "Создана {glyph} <b>{name}</b>, переключаемся на неё.\n{tagline}\n"
              "Отправьте сообщение, чтобы начать · /rename — переименовать · "
              "/sessions — переключиться.",
    },
    "session.new_pick": {
        "en": "Create a new session — pick the type (it's fixed for the "
              "session's life):\n{tagline_chat}\n{tagline_code}",
        "ru": "Создать новую сессию — выберите тип (он фиксируется на всё время "
              "сессии):\n{tagline_chat}\n{tagline_code}",
    },
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
        "en": "<code>{sid}</code> {icon} {name} — <b>{mode}</b> · {date}{mark}",
        "ru": "<code>{sid}</code> {icon} {name} — <b>{mode}</b> · {date}{mark}",
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
    "mode.show": {
        "en": "This session is {glyph} <b>{mode}</b>. {tagline}",
        "ru": "Эта сессия — {glyph} <b>{mode}</b>. {tagline}",
    },
    "mode.hint_upgrade": {
        "en": "Need a terminal or files? Upgrade with /code — the conversation carries over.",
        "ru": "Нужен терминал или файлы? Повысьте до /code — диалог сохранится.",
    },
    "mode.hint_downgrade": {
        "en": "Back to a plain chat with /chat — workdir files are kept.",
        "ru": "Вернуться к обычному чату — /chat — файлы рабочей папки сохранятся.",
    },
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
    "files.header": {"en": "📂 <code>{dir}</code>", "ru": "📂 <code>{dir}</code>"},
    "files.empty": {
        "en": "📂 <code>{dir}</code> — empty or not created yet.",
        "ru": "📂 <code>{dir}</code> — пусто или ещё не создана.",
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
              "the <b>1M-token</b> context window (chat or code). ⚠️ That beta is "
              "currently ignored under the Pro/Max subscription, so it's a no-op for "
              "now. Your conversation persists across restarts either way. Toggle with "
              "<code>/memory on</code> / <code>/memory off</code>.",
        "ru": "Большая память: <b>{current}</b>.\nКогда <b>вкл</b>, эта сессия "
              "запрашивает окно контекста на <b>1M токенов</b> (чат или код). ⚠️ Эта "
              "бета сейчас игнорируется на подписке Pro/Max, так что пока ни на что не "
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
        "en": "Big memory <b>on</b> — this chat session now uses the 1M-token "
              "context window.{note}",
        "ru": "Большая память <b>вкл</b> — эта чат-сессия теперь использует окно "
              "контекста на 1M токенов.{note}",
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
        "en": "ask for approval before dangerous tools (Bash/Write/Edit)",
        "ru": "спрашивать подтверждение перед опасными инструментами (Bash/Write/Edit)",
    },
    "perm.help.auto-edits": {
        "en": "auto-approve file edits, still ask for the rest",
        "ru": "автоматически одобрять правки файлов, остальное спрашивать",
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
        "en": "Send: <code>&lt;id|@user&gt; chat|code</code> (or /cancel).",
        "ru": "Отправьте: <code>&lt;id|@user&gt; chat|code</code> (или /cancel).",
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
        "en": "🔒 Daily token limit reached (<b>{used}/{cap}</b>). It frees up as your last 24h of usage ages out.",
        "ru": "🔒 Дневной лимит токенов исчерпан (<b>{used}/{cap}</b>). Освободится по мере устаревания последних 24 часов.",
    },
    "access.rate_week_exceeded": {
        "en": "🔒 Weekly token limit reached (<b>{used}/{cap}</b>). It frees up as your last 7 days age out.",
        "ru": "🔒 Недельный лимит токенов исчерпан (<b>{used}/{cap}</b>). Освободится по мере устаревания последних 7 дней.",
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
        "en": "<i>The owner is always code, never expires, is uncapped, and may use max effort.</i>",
        "ru": "<i>Владелец всегда code, не истекает, без лимитов и может использовать max effort.</i>",
    },
    "usercard.not_found": {"en": "User not found.", "ru": "Пользователь не найден."},
    "usercard.btn_level": {"en": "Level: {level} → {next}", "ru": "Уровень: {level} → {next}"},
    "usercard.btn_memory": {"en": "🧠 Memory: {state}", "ru": "🧠 Память: {state}"},
    "usercard.btn_maxeffort": {"en": "⚡ Max effort: {state}", "ru": "⚡ Max effort: {state}"},
    "usercard.btn_tools": {"en": "🧰 Tools: {val}", "ru": "🧰 Инструменты: {val}"},
    "usercard.btn_expiry": {"en": "⏳ Set expiry…", "ru": "⏳ Срок доступа…"},
    "usercard.btn_day": {"en": "📊 Day limit…", "ru": "📊 Лимит/день…"},
    "usercard.btn_week": {"en": "📅 Week limit…", "ru": "📅 Лимит/неделя…"},
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
    "status.cache": {
        "en": "Cache window (5 min): ~{secs}s left",
        "ru": "Окно кэша (5 мин): осталось ~{secs}с",
    },
    "status.limits_header": {
        "en": "<b>Subscription limits</b>",
        "ru": "<b>Лимиты подписки</b>",
    },
    "status.trend_header": {"en": "<b>Usage trend</b>", "ru": "<b>Тренд использования</b>"},
    "status.totals_header": {
        "en": "<b>Usage (session lifetime)</b>",
        "ru": "<b>Использование (за всё время сессии)</b>",
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
    "recap.empty": {
        "en": "No conversation logged yet in this session.",
        "ru": "В этой сессии ещё нет записанного разговора.",
    },
    "recap.empty_has_context": {
        "en": "No transcript is saved for this session yet — earlier turns predate "
              "transcript logging, so /recap and /history can't replay them, but the "
              "model may still recall them from its own context. New messages are saved "
              "from now on.",
        "ru": "Для этой сессии ещё нет сохранённой расшифровки — ранние сообщения были "
              "до ведения журнала, поэтому /recap и /history не могут их показать, но "
              "модель всё ещё может помнить их из своего контекста. Новые сообщения "
              "сохраняются с этого момента.",
    },
    "recap.header": {
        "en": "<b>Recap — last exchange</b>",
        "ru": "<b>Сводка — последний обмен</b>",
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
        "en": "Cleared {n} queued message(s). The current run keeps going — use "
              "<code>/stop</code> to halt it.",
        "ru": "Очищено сообщений в очереди: {n}. Текущий запуск продолжается — "
              "используйте <code>/stop</code>, чтобы остановить его.",
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
        "en": "Rate limit reached. Please try again later.",
        "ru": "Достигнут лимит запросов. Попробуйте позже.",
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
    "cmd.new": {"en": "➕ New chat session", "ru": "➕ Новая сессия (чат)"},
    "cmd.code": {"en": "🟩 Upgrade this session to code", "ru": "🟩 Повысить сессию до кода"},
    "cmd.chat": {"en": "💬 Downgrade this session to chat", "ru": "💬 Понизить сессию до чата"},
    "cmd.newchat": {"en": "💬 New chat session", "ru": "💬 Новая чат-сессия"},
    "cmd.newcode": {"en": "🟩 New code session", "ru": "🟩 Новая код-сессия"},
    "cmd.sessions": {
        "en": "Browse / switch / delete sessions",
        "ru": "Обзор / переключение / удаление сессий",
    },
    "cmd.rename": {"en": "Rename the current session", "ru": "Переименовать текущую сессию"},
    "cmd.status": {"en": "Current session info", "ru": "Сведения о текущей сессии"},
    "cmd.stop": {"en": "Stop the current reply", "ru": "Остановить текущий ответ"},
    "cmd.retry": {"en": "Re-run the last prompt", "ru": "Повторить последний запрос"},
    "cmd.clear": {"en": "Clear the session context", "ru": "Очистить контекст сессии"},
    "cmd.reset": {"en": "Clear the session context (alias of /clear)", "ru": "Очистить контекст (синоним /clear)"},
    "cmd.model": {
        "en": "Switch model: opus | sonnet | haiku",
        "ru": "Сменить модель: opus | sonnet | haiku",
    },
    "cmd.effort": {"en": "Reasoning depth: low … max", "ru": "Глубина рассуждений: low … max"},
    "cmd.fork": {
        "en": "Branch this session into a new one",
        "ru": "Ответвить эту сессию в новую",
    },
    "cmd.memory": {
        "en": "1M context window (chat): on | off",
        "ru": "Окно контекста 1M (чат): on | off",
    },
    "cmd.permissions": {
        "en": "Code tool policy: ask | auto-edits | plan",
        "ru": "Политика инструментов кода: ask | auto-edits | plan",
    },
    "cmd.cwd": {"en": "Working directory (code sessions)", "ru": "Рабочая папка (код-сессии)"},
    "cmd.dirs": {"en": "Extra code directories", "ru": "Доп. папки для кода"},
    "cmd.files": {"en": "Browse the working-dir tree (code)", "ru": "Дерево рабочей папки (код)"},
    "cmd.export": {"en": "Export working-dir files as .zip (code)", "ru": "Экспорт файлов рабочей папки (.zip, код)"},
    "cmd.sandbox": {"en": "Toggle this code session's sandbox (owner)", "ru": "Песочница код-сессии вкл/выкл (владелец)"},
    "cmd.maxturns": {"en": "Cap agentic turns (code)", "ru": "Лимит агентных ходов (код)"},
    "cmd.recap": {"en": "Show the last exchange", "ru": "Показать последний обмен"},
    "cmd.history": {
        "en": "Export this session's transcript",
        "ru": "Выгрузить расшифровку этой сессии",
    },
    "cmd.usage": {"en": "Subscription-usage display", "ru": "Показ использования подписки"},
    "cmd.context": {"en": "Context-window usage", "ru": "Использование окна контекста"},
    "cmd.queue": {"en": "Show the pending-prompt queue", "ru": "Показать очередь запросов"},
    "cmd.clearqueue": {"en": "Clear the pending queue", "ru": "Очистить очередь"},
    "cmd.stream": {"en": "Live streaming: on | off", "ru": "Живой стриминг: on | off"},
    "cmd.settings": {"en": "Open the settings menu", "ru": "Открыть меню настроек"},
    "cmd.tools": {"en": "Configure this session's tools", "ru": "Настроить инструменты сессии"},
    "cmd.language": {"en": "Choose the interface language", "ru": "Выбрать язык интерфейса"},
    "cmd.help": {"en": "Show help", "ru": "Показать справку"},
    "cmd.whoami": {"en": "Show your id and username", "ru": "Показать ваш id и username"},
    "cmd.auto": {
        "en": "Run code tools without asking (owner)",
        "ru": "Запускать инструменты кода без вопросов (владелец)",
    },
    "cmd.allow": {"en": "Allow a user (owner)", "ru": "Разрешить пользователя (владелец)"},
    "cmd.deny": {"en": "Remove a user (owner)", "ru": "Удалить пользователя (владелец)"},
    "cmd.users": {"en": "List allowed users (owner)", "ru": "Список пользователей (владелец)"},
    "cmd.level": {"en": "Set a user's access level (owner)", "ru": "Уровень доступа (владелец)"},
    "cmd.expire": {"en": "Set a user's access expiry (owner)", "ru": "Срок доступа (владелец)"},
    "cmd.limit": {"en": "Top up a user's token grant (owner)", "ru": "Пополнить лимит токенов (владелец)"},
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
