"""Localization for the bot's own user-facing strings.

- English is the canonical, always-complete locale
- Missing entries in other locales fall back to English
- Covers the interface only, not Claude's answers
- Resolved per-user locale is cached to avoid DB hits
"""

from __future__ import annotations

# Canonical source locale and fallback for missing translations.
DEFAULT_LANG = "en"

# Supported locales and their native display names.
# - Add the matching column to every `CATALOG` row
LANGUAGES: dict[str, str] = {
    "en": "English",
    "ru": "Русский",
}


def normalize_lang(code: str | None) -> str:
    """Map a Telegram `language_code` to a supported locale."""
    if not code:
        return DEFAULT_LANG
    base = str(code).split("-", 1)[0].strip().lower()
    return base if base in LANGUAGES else DEFAULT_LANG


# Per-user language cache, resolved once by middleware.
_user_lang: dict[int, str] = {}


def has_lang(user_id: int) -> bool:
    """True if this user's locale is already resolved."""
    return user_id in _user_lang


def cached_lang(user_id: int) -> str:
    """Return the user's resolved locale, or the default."""
    return _user_lang.get(user_id, DEFAULT_LANG)


def remember_lang(user_id: int, lang: str) -> None:
    """Cache a user's locale, validated against `LANGUAGES`."""
    _user_lang[user_id] = lang if lang in LANGUAGES else DEFAULT_LANG


def forget_lang(user_id: int) -> None:
    """Drop a cached locale to force a re-read."""
    _user_lang.pop(user_id, None)


# The l10n table: rows are keys, columns are languages.
# - Every row needs an "en" entry
# - HTML tags and placeholders must match across columns
CATALOG: dict[str, dict[str, str]] = {
    # -- common atoms --
    "common.error": {"en": "Error.", "ru": "Ошибка."},
    "common.switched": {"en": "Switched.", "ru": "Переключено."},
    "common.created": {"en": "Created.", "ru": "Создано."},
    # Shown to users while the maintenance sentinel is up.
    "maintenance.notice": {
        "en": "🛠 The service is updating and will be back in ~15 minutes. Your sessions and history are saved — please try again shortly.",
        "ru": "🛠 Сервис обновляется и вернётся примерно через 15 минут. Ваши сессии и история сохранены — попробуйте чуть позже.",
    },
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

    # -- generic buttons --
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
    # -- /sessions options menu and browser actions --
    "btn.switch": {"en": "✅ Switch", "ru": "✅ Переключиться"},
    "btn.recap": {"en": "📋 Recap", "ru": "📋 Сводка"},
    "btn.status": {"en": "ℹ️ Status", "ru": "ℹ️ Статус"},
    "btn.rename": {"en": "✏️ Rename", "ru": "✏️ Переименовать"},
    "btn.export": {"en": "📄 Export", "ru": "📄 Экспорт"},
    "btn.transcript": {"en": "📄 Transcript", "ru": "📄 Транскрипт"},
    "btn.export_files": {"en": "📦 Export files", "ru": "📦 Экспорт файлов"},
    "btn.favorite": {"en": "⭐ Favorite", "ru": "⭐ В избранное"},
    "btn.unfavorite": {"en": "☆ Unfavorite", "ru": "☆ Из избранного"},
    # Plus sign marks create actions, unlike an untitled session.
    "btn.new_chat": {"en": "➕ New chat", "ru": "➕ Новый чат"},
    "btn.new_code": {"en": "➕ New code", "ru": "➕ Новый код"},

    # -- session mode words and taglines --
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
    # Terminal-style prompt line appended when a cwd is known.
    "mode.tagline_where": {
        "en": "\n<code>{cwd} $</code>",
        "ru": "\n<code>{cwd} $</code>",
    },

    # -- /help, /start --
    # - Help is generated from the command registry
    # - i18n holds only intro, group headers, and footer
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

    # -- /language --
    "lang.title": {
        "en": "🌐 <b>Language</b>\nCurrent: <b>{name}</b>\nTap to change:",
        "ru": "🌐 <b>Язык</b>\nТекущий: <b>{name}</b>\nНажмите, чтобы изменить:",
    },
    "lang.set": {
        "en": "🌐 Interface language set to <b>{name}</b>.",
        "ru": "🌐 Язык интерфейса: <b>{name}</b>.",
    },
    "lang.row": {"en": "🌐 Language: {name} ▸", "ru": "🌐 Язык: {name} ▸"},

    # -- /settings --
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
    # The /settings Admin sub-page: retention, global toggles, user-management launchers.
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
    # Global idle window before a fresh session starts.
    "admin.idle_btn": {"en": "💤 New session after idle: {val} ▸",
                       "ru": "💤 Новая сессия после простоя: {val} ▸"},
    "admin.idle_title": {
        "en": "💤 <b>New session after idle</b>\nAfter this long with no activity, the next "
              "message starts a fresh session (clean context; workdir files are kept):",
        "ru": "💤 <b>Новая сессия после простоя</b>\nПосле такого простоя следующее сообщение "
              "начинает новую сессию (чистый контекст; файлы в рабочей папке сохраняются):"},
    "admin.idle_saved": {"en": "✓ New session after idle: {val}",
                         "ru": "✓ Новая сессия после простоя: {val}"},
    "admin.idle_off": {"en": "Off (never)", "ru": "Выкл (никогда)"},
    "admin.idle_mins": {"en": "{n} min", "ru": "{n} мин"},
    "admin.idle_hours": {"en": "{n} h", "ru": "{n} ч"},
    # Admin page for the Claude Code CLI: version, update schedule.
    "admin.cli_btn": {"en": "🔄 CLI update: {val} ▸", "ru": "🔄 Обновление CLI: {val} ▸"},
    "admin.cli_title": {
        "en": "🔄 <b>Claude Code CLI</b>\nVersion: <code>{ver}</code>\nLast check: {last}",
        "ru": "🔄 <b>Claude Code CLI</b>\nВерсия: <code>{ver}</code>\nПоследняя проверка: {last}"},
    "admin.cli_ver_jail": {"en": "{host} (sandbox copy: {jail})",
                           "ru": "{host} (копия в песочнице: {jail})"},
    "admin.cli_never": {"en": "never", "ru": "ещё не было"},
    "admin.cli_res_failed": {"en": "⚠️ The last update failed: {detail}",
                             "ru": "⚠️ Последнее обновление не удалось: {detail}"},
    "admin.cli_res_updated": {"en": "✅ Updated {before} → {after}",
                              "ru": "✅ Обновлено: {before} → {after}"},
    "admin.cli_res_current": {"en": "✅ Up to date ({ver})", "ru": "✅ Версия актуальна ({ver})"},
    "admin.cli_pick": {
        "en": "The bot runs <code>claude update</code> once a day at this time (UTC). Sessions "
              "move to a new version without cutting a reply: idle ones at once, busy ones "
              "after their answer.",
        "ru": "Бот запускает <code>claude update</code> раз в день в это время (UTC). Сессии "
              "переходят на новую версию, не обрывая ответ: простаивающие — сразу, занятые — "
              "после своего ответа."},
    "admin.cli_off": {"en": "Off", "ru": "Выкл"},
    "admin.cli_daily": {"en": "{time} UTC", "ru": "{time} UTC"},
    "admin.cli_now": {"en": "🔄 Check now", "ru": "🔄 Проверить сейчас"},
    "admin.cli_saved": {"en": "✓ CLI update: {val}", "ru": "✓ Обновление CLI: {val}"},
    "admin.cli_checking": {"en": "Checking for a CLI update…", "ru": "Проверяю обновление CLI…"},
    "admin.ret_never": {"en": "♾ Never (keep forever)", "ru": "♾ Никогда (хранить всегда)"},
    "admin.ret_1mo": {"en": "1 month", "ru": "1 месяц"},
    "admin.ret_3mo": {"en": "3 months", "ru": "3 месяца"},
    "admin.ret_6mo": {"en": "6 months", "ru": "6 месяцев"},
    "admin.ret_12mo": {"en": "12 months", "ru": "12 месяцев"},
    "admin.ret_days": {"en": "{n} days", "ru": "{n} дн."},
    "admin.tog_codesplit": {"en": "🧩 Code split: {val}", "ru": "🧩 Разбивка кода: {val}"},
    "admin.tog_workingplate": {"en": "⏳ Working plate: {val}", "ru": "⏳ Плашка работы: {val}"},
    "admin.name_codesplit": {"en": "🧩 Code split", "ru": "🧩 Разбивка кода"},
    "admin.name_workingplate": {"en": "⏳ Working plate", "ru": "⏳ Плашка работы"},
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
    # Warm-cache post-reply note and auto-compact label.
    "settings.row_hot_cache_timer": {"en": "🔥 Warm-cache note: {val}", "ru": "🔥 Заметка о тёплом кэше: {val}"},
    "settings.row_auto_compact": {"en": "📦 Auto-compact: {val}", "ru": "📦 Автокомпакт: {val}"},
    "settings.row_ctx_status": {"en": "🧠 Live context size: {val}", "ru": "🧠 Размер контекста в плашке: {val}"},
    # Live task-list card toggle for code sessions.
    "settings.row_todo_card": {"en": "📋 Live task list: {val}", "ru": "📋 Живой список задач: {val}"},
    "stream.context": {"en": "🧠 context {n}", "ru": "🧠 контекст {n}"},
    # Draft stand-in while a table is still being written.
    "stream.table_building": {"en": "📊 Building a table… {rows}", "ru": "📊 Собираю таблицу… {rows}"},
    # Bare name for the usage-display picker title.
    "settings.usage_name": {"en": "📊 Usage display", "ru": "📊 Использование"},
    # Header for the per-session Tools grid.
    "settings.tools_title": {
        "en": "🧰 <b>Tools</b>\nToggle the tools this session may use.",
        "ru": "🧰 <b>Инструменты</b>\nВключите инструменты, доступные этой сессии.",
    },
    # Owner option-admin page and access levels.
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
    # File cabinet emoji means memory/context; brain is for MODEL.
    # - Dedicated max_turns label avoids duplicate "Model" rows
    "settings.row_maxturns": {"en": "🔁 Max turns: {val} ▸", "ru": "🔁 Лимит ходов: {val} ▸"},
    # Sandbox is owner-only and hidden from non-owners.
    # - The test-tube emoji is canonical for sandbox
    "settings.row_sandbox": {"en": "🧪 Sandbox: {val} ▸", "ru": "🧪 Песочница: {val} ▸"},
    # Registry-driven, scope-tabbed /settings hub.
    "settings.tab_session": {"en": "📍 This session", "ru": "📍 Эта сессия"},
    "settings.tab_user": {"en": "👤 My defaults", "ru": "👤 Мои умолчания"},
    "settings.tab_global": {"en": "🌍 Global", "ru": "🌍 Глобально"},
    # Short badges showing which scope supplies a value.
    "settings.badge_session": {"en": "this session", "ru": "эта сессия"},
    "settings.badge_user": {"en": "my default", "ru": "моё умолчание"},
    "settings.badge_global": {"en": "global default", "ru": "глобально"},
    "settings.v2_header": {
        "en": "⚙️ <b>Settings</b> · {tab}\nTap a setting to change it.",
        "ru": "⚙️ <b>Настройки</b> · {tab}\nНажмите настройку, чтобы изменить её.",
    },
    # One hub row: name, resolved value, source badge.
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

    # -- session create, switch, rename, delete --
    # - `{meta}` is the CLI's model and effort line
    # - Confirmation is only glyph plus model line
    "session.created": {"en": "{glyph} {meta}", "ru": "{glyph} {meta}"},
    # Model with version plus effort, for /new and thinking tag.
    "session.model_line": {"en": "{model} · {effort}", "ru": "{model} · {effort}"},
    "session.renamed": {
        "en": "Session renamed to <b>{name}</b>.",
        "ru": "Сессия переименована в <b>{name}</b>.",
    },
    "session.rename_prompt": {
        "en": "✏️ Send the new session name (or /cancel).",
        "ru": "✏️ Отправьте новое имя сессии (или /cancel).",
    },
    # Reserved: idle rotation is silent, so this notice is unused.
    "session.idle_reset": {
        "en": "🆕 Started a fresh session — the previous one was idle for over {mins} min, "
              "so I'm not carrying its context. Files in the workdir are kept.",
        "ru": "🆕 Начал новую сессию — предыдущая простаивала больше {mins} мин, поэтому её "
              "контекст не переношу. Файлы в рабочей папке сохранены.",
    },
    # Default names read "Untitled"; the mode glyph shows type.
    # - Avoids colliding with the create buttons
    "session.default_name_chat": {"en": "Not named yet", "ru": "Пока без названия"},
    "session.default_name_code": {"en": "Not named yet", "ru": "Пока без названия"},
    "session.first_default": {"en": "Not named yet", "ru": "Пока без названия"},
    # Legacy placeholder names of untitled sessions, pipe-separated.
    # - Never rendered; read by `placeholder_session_names()`
    "session.legacy_default_names": {
        "en": "Chat session|Code session|Session 1|New chat|New code session|Untitled",
        "ru": "Чат-сессия|Код-сессия|Сессия 1|Новый чат|Новая код-сессия|Без названия",
    },
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
    # Session card shows the effort tier beside the model.
    "session.card_meta": {
        "en": "Model: <code>{model}</code> · Effort: <code>{effort}</code>",
        "ru": "Модель: <code>{model}</code> · Усилие: <code>{effort}</code>",
    },
    # Same line for a model that takes no effort level.
    "session.card_meta_model": {
        "en": "Model: <code>{model}</code>",
        "ru": "Модель: <code>{model}</code>",
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

    # -- /sessions browser --
    "sessions.head_dm": {"en": "🗂 <b>Your sessions</b>", "ru": "🗂 <b>Ваши сессии</b>"},
    "sessions.head_group": {"en": "🗂 <b>Topics</b>", "ru": "🗂 <b>Темы</b>"},
    "sessions.head_search": {"en": " · search “{kw}”", "ru": " · поиск «{kw}»"},
    "sessions.head_total": {"en": " · {total} total", "ru": " · всего {total}"},
    "sessions.idle_rotated": {  # passive note after auto-rotation
        "en": "🆕 <i>Started a fresh session after a break — your previous one is saved below.</i>",
        "ru": "🆕 <i>Начата новая сессия после перерыва — предыдущая сохранена ниже.</i>",
    },
    "sessions.row": {
        # The list leads with icon and name only.
        "en": "{icon} <b>{name}</b>{mark}",
        "ru": "{icon} <b>{name}</b>{mark}",
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
    # Toast after a New-chat tap nudges the user to type.
    "sessions.new_chat_toast": {
        "en": "✨ New chat — just type your question.",
        "ru": "✨ Новый чат — просто напишите вопрос.",
    },

    # -- /mode --
    # - /mode toggles the type directly, so no hint rows
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

    # -- /model --
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

    # -- /effort --
    # - Levels are the CLI's list for the model
    "effort.default_label": {"en": "default ({level})", "ru": "по умолчанию ({level})"},
    "effort.show": {
        "en": "Reasoning effort: <b>{cur}</b>.\nSet with "
              "<code>/effort {levels}</code> "
              "(<code>/effort default</code> to reset). Higher = deeper thinking, "
              "more tokens.",
        "ru": "Глубина рассуждений: <b>{cur}</b>.\nЗадайте через "
              "<code>/effort {levels}</code> "
              "(<code>/effort default</code> — сброс). Выше = глубже мышление, "
              "больше токенов.",
    },
    "effort.reset": {
        "en": "Reasoning effort reset to default.{defer}",
        "ru": "Глубина рассуждений сброшена к значению по умолчанию.{defer}",
    },
    "effort.usage": {
        "en": "Usage: <code>/effort {levels}</code>.",
        "ru": "Использование: <code>/effort {levels}</code>.",
    },
    "effort.unsupported": {
        "en": "<b>{model}</b> has no reasoning-effort levels.",
        "ru": "У <b>{model}</b> нет уровней глубины рассуждений.",
    },
    # Opportunistic display names for effort levels.
    # - The CLI supplies the level set
    # - A level without a row shows its own name
    "effort.level.low": {"en": "low", "ru": "низкое"},
    "effort.level.medium": {"en": "medium", "ru": "среднее"},
    "effort.level.high": {"en": "high", "ru": "высокое"},
    "effort.level.xhigh": {"en": "xhigh", "ru": "очень высокое"},
    "effort.level.max": {"en": "max", "ru": "максимальное"},
    "effort.set": {
        "en": "Reasoning effort: <b>{val}</b>.{defer}",
        "ru": "Глубина рассуждений: <b>{val}</b>.{defer}",
    },
    "effort.pick": {
        "en": "Reasoning effort: <b>{cur}</b>. Pick one:",
        "ru": "Глубина рассуждений: <b>{cur}</b>. Выберите:",
    },

    # -- /files (read-only working-dir tree) --
    # - Shows the session name, not the host path
    "files.header": {"en": "📂 <b>{name}</b>", "ru": "📂 <b>{name}</b>"},
    "files.empty": {
        "en": "📂 <b>{name}</b> — no files yet.",
        "ru": "📂 <b>{name}</b> — пока нет файлов.",
    },

    # -- /export (zip the code-session working dir) --
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

    # -- /sandbox --
    # - Sandbox is mandatory; the toggle is retired
    "sandbox.mandatory": {
        "en": "🔒 The sandbox is <b>always on</b> for every session (chat and code) — it can't be turned off. Each session runs in its own isolated jail.",
        "ru": "🔒 Песочница <b>всегда включена</b> для каждой сессии (chat и code) — отключить нельзя. Каждая сессия работает в собственном изолированном джейле.",
    },

    # -- /secret (per-session service credentials) --
    "secret.help": {
        "en": "🔐 <b>Session secrets</b>\nStored: {names}\n\nSend <code>NAME=VALUE</code> "
              "to add one (e.g. <code>GH_TOKEN=ghp_xxx</code>), or <code>/cancel</code>.\n"
              "Clear with <code>/secret clear</code> (all) or <code>/secret clear NAME</code> "
              "(one).\nSecrets are injected as environment variables into <b>this session's "
              "jail only</b> — not other sessions. Values are never shown again.",
        "ru": "🔐 <b>Секреты сессии</b>\nСохранено: {names}\n\nОтправьте <code>NAME=VALUE</code>, "
              "чтобы добавить (напр. <code>GH_TOKEN=ghp_xxx</code>), или <code>/cancel</code>.\n"
              "Очистить: <code>/secret clear</code> (все) или <code>/secret clear NAME</code> "
              "(один).\nСекреты внедряются как переменные окружения <b>только в jail этой "
              "сессии</b> — не в другие сессии. Значения больше не показываются.",
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
    # Detailed how-to behind the "How to use" button on /secret.
    "secret.guide": {
        "en": (
            "🔐 <b>Session secrets — how to use</b>\n\n"
            "A secret is any <code>NAME=VALUE</code> pair. It is stored for THIS session "
            "only and injected as an environment variable into this session's sandbox on "
            "the next turn, so tools like <code>gh</code>, <code>git</code>, "
            "<code>npm</code> or <code>aws</code> can authenticate. The value is "
            "write-only — it is never shown again, and the agent can't read the secrets "
            "file itself.\n\n"
            "<b>Example — connect GitHub over HTTPS</b>\n"
            "1. Create a token at <code>github.com/settings/tokens</code> → "
            "<i>Fine-grained token</i>, scoped to just the repo you need "
            "(Contents: Read and write). Copy it (starts with <code>github_pat_</code> "
            "or <code>ghp_</code>).\n"
            "2. Send it here: <code>GH_TOKEN=github_pat_xxx</code>\n"
            "3. Next turn, ask the agent to use it — e.g. <i>clone github.com/me/repo and "
            "push a branch</i>. <code>gh</code> reads <code>GH_TOKEN</code> "
            "automatically; for plain git use <code>gh auth setup-git</code> or an "
            "<code>https://x-access-token:$GH_TOKEN@github.com/...</code> URL.\n\n"
            "⚠️ <b>HTTPS only — SSH is not supported in the bot.</b> There is no way to "
            "install an SSH key in the sandbox (its home is wiped each turn), so always "
            "use an HTTPS token.\n\n"
            "Other uses: <code>NPM_TOKEN</code>, <code>AWS_ACCESS_KEY_ID</code> / "
            "<code>AWS_SECRET_ACCESS_KEY</code>, <code>OPENAI_API_KEY</code>, "
            "<code>DATABASE_URL</code>, ... (the remote host must be on the sandbox's "
            "egress allowlist).\n\n"
            "🔒 <b>Trust:</b> secrets are stored on the machine that runs this bot, so "
            "its operator can technically read them. Use narrowly-scoped, revocable "
            "tokens — never a master password.\n\n"
            "Manage: <code>/secret</code> (list names) · "
            "<code>/secret clear NAME</code> · <code>/secret clear</code> (all)."
        ),
        "ru": (
            "🔐 <b>Секреты сессии — как пользоваться</b>\n\n"
            "Секрет — это пара <code>NAME=VALUE</code>. Хранится только для ЭТОЙ сессии и "
            "на следующем ходу внедряется как переменная окружения в песочницу сессии, "
            "чтобы инструменты вроде <code>gh</code>, <code>git</code>, <code>npm</code> "
            "или <code>aws</code> могли авторизоваться. Значение write-only — больше не "
            "показывается, и сам агент файл секретов не читает.\n\n"
            "<b>Пример — подключить GitHub по HTTPS</b>\n"
            "1. Создайте токен на <code>github.com/settings/tokens</code> → "
            "<i>Fine-grained token</i>, с доступом только к нужному репозиторию "
            "(Contents: Read and write). Скопируйте (начинается с "
            "<code>github_pat_</code> или <code>ghp_</code>).\n"
            "2. Пришлите сюда: <code>GH_TOKEN=github_pat_xxx</code>\n"
            "3. На следующем ходу попросите агента это использовать — напр. "
            "<i>склонируй github.com/me/repo и запушь ветку</i>. <code>gh</code> читает "
            "<code>GH_TOKEN</code> сам; для чистого git — <code>gh auth setup-git</code> "
            "или URL <code>https://x-access-token:$GH_TOKEN@github.com/...</code>.\n\n"
            "⚠️ <b>Только HTTPS — SSH в боте не поддерживается.</b> Положить SSH-ключ в "
            "песочницу нельзя (её домашняя папка стирается каждый ход), поэтому всегда "
            "используйте HTTPS-токен.\n\n"
            "Другое применение: <code>NPM_TOKEN</code>, <code>AWS_ACCESS_KEY_ID</code> / "
            "<code>AWS_SECRET_ACCESS_KEY</code>, <code>OPENAI_API_KEY</code>, "
            "<code>DATABASE_URL</code>, ... (удалённый хост должен быть в egress-allowlist "
            "песочницы).\n\n"
            "🔒 <b>Доверие:</b> секреты хранятся на машине, где запущен бот, поэтому её "
            "оператор технически может их прочитать. Берите узкие отзываемые токены — "
            "никогда не мастер-пароль.\n\n"
            "Управление: <code>/secret</code> (список имён) · "
            "<code>/secret clear NAME</code> · <code>/secret clear</code> (всё)."
        ),
    },
    "secret.btn_guide": {"en": "📖 How to use", "ru": "📖 Как использовать"},
    "settings.row_secret": {"en": "🔐 Session secrets ▸", "ru": "🔐 Секреты сессии ▸"},
    # -- /shell (shell-mode overlay) --
    "shell.code_only": {
        "en": "⌨️ Shell mode is available in <b>code</b> sessions only.",
        "ru": "⌨️ Режим shell доступен только в <b>code</b>-сессиях.",
    },
    "shell.on": {
        "en": "⌨️ <b>Shell mode ON.</b> Every message now runs as a command in this "
              "session's sandbox — no AI, no tokens. <code>cd</code> and environment "
              "persist between commands, and commands that ask for input work (you'll get "
              "a key keypad). Full-screen apps (<code>vim</code>, <code>top</code>) aren't "
              "supported. Send <code>/shell</code> again to detach — the shell (and any "
              "running command) keeps going in the background.",
        "ru": "⌨️ <b>Режим shell ВКЛ.</b> Каждое сообщение теперь выполняется как команда "
              "в песочнице сессии — без ИИ и без токенов. <code>cd</code> и переменные "
              "окружения сохраняются между командами, а команды, запрашивающие ввод, "
              "работают (появится клавиатура клавиш). Полноэкранные программы "
              "(<code>vim</code>, <code>top</code>) не поддерживаются. Отправьте "
              "<code>/shell</code> ещё раз, чтобы отсоединиться — shell (и запущенная "
              "команда) продолжит работать в фоне.",
    },
    "shell.off": {
        "en": "⌨️ <b>Shell mode OFF.</b> Back to talking with the agent.",
        "ru": "⌨️ <b>Режим shell ВЫКЛ.</b> Снова общаемся с агентом.",
    },
    "shell.accidental": {
        "en": "<i>(command not found — you're in shell mode; send /shell to exit)</i>",
        "ru": "<i>(команда не найдена — вы в режиме shell; отправьте /shell для выхода)</i>",
    },
    # Line-interactive commands work.
    # - Full-screen TUIs can't render in a bubble; refused
    "shell.interactive": {
        "en": "🖥 Full-screen programs (<code>vim</code>, <code>top</code>, <code>less</code>, "
              "<code>man</code>, …) can't render in a chat — they're not supported. Use a "
              "non-TUI form (e.g. <code>cat</code> instead of <code>less</code>).",
        "ru": "🖥 Полноэкранные программы (<code>vim</code>, <code>top</code>, <code>less</code>, "
              "<code>man</code>, …) не отображаются в чате — не поддерживаются. Используй "
              "не-TUI вариант (например <code>cat</code> вместо <code>less</code>).",
    },
    # A command paused for input receives the next message.
    "shell.awaiting": {
        "en": "⌨️ <i>Waiting for input — use the keys below, or type to filter a list / send a "
              "line. (Typed key fallback: <code>.up</code> <code>.down</code> <code>.enter</code>, "
              "chainable: <code>.down .enter</code>.) /shell to cancel.</i>",
        "ru": "⌨️ <i>Жду ввод — жми кнопки ниже, либо печатай для фильтра / отправь строку. "
              "(Текстом тоже можно: <code>.up</code> <code>.down</code> <code>.enter</code>, "
              "цепочкой: <code>.down .enter</code>.) /shell — отмена.</i>",
    },
    # The persistent shell died while awaiting input.
    # - The message was input, so it is dropped
    "shell.ended": {
        "en": "⚠️ <i>The shell ended while a program was waiting for input, so your input "
              "was discarded (not run as a command). Re-run the command to continue.</i>",
        "ru": "⚠️ <i>Shell завершился, пока программа ждала ввод — ваш ввод отброшен (не "
              "выполнен как команда). Запустите команду заново, чтобы продолжить.</i>",
    },
    # Startup owner alert when the uid doctor finds a collision.
    "admin.uid_collision_alert": {
        "en": "⚠️ <b>Sandbox uid check</b> · <i>{ts}</i>\n{count} host uid(s) own more than one "
              "session's files on disk — a per-session isolation gap. Usually transient: "
              "the affected sessions re-chown to a unique uid on their next turn.\n{detail}",
        "ru": "⚠️ <b>Проверка uid песочниц</b> · <i>{ts}</i>\n{count} host-uid владеют файлами более "
              "чем одной сессии на диске — брешь в изоляции сессий. Обычно временно: "
              "затронутые сессии перечоунятся на уникальный uid на следующем ходу.\n{detail}",
    },

    # -- /maxturns --
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

    # -- /dirs --
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

    # -- /fork --
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

    # -- /memory --
    # - /memory is retired; these rows are unused
    "forget.empty": {
        "en": "📝 Session memory is already empty — nothing to forget.",
        "ru": "📝 Память сессии уже пуста — забывать нечего.",
    },
    "forget.done": {
        "en": "📝 Session memory cleared (<b>{n}</b> chars).{note}",
        "ru": "📝 Память сессии очищена (<b>{n}</b> символов).{note}",
    },

    # -- /cwd --
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

    # -- /permissions --
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
    # The "ask" permission is dropped; auto-edits is the floor.
    # - The sandbox makes per-tool prompting unnecessary
    "perm.help.auto-edits": {
        "en": "default — auto-run edits & safe commands; ask only for push, destructive or web/outbound actions",
        "ru": "по умолчанию — авто-запуск правок и безопасных команд; спрашивать только push, разрушительные и сетевые действия",
    },
    "perm.help.plan": {
        "en": "plan only, do not run tools",
        "ru": "только планирование, без запуска инструментов",
    },
    "perm.help.full-access": {
        "en": "run everything unattended, no approvals — fast, but uses more of your "
              "usage limit; the sandbox still confines it to this session",
        "ru": "выполнять всё без подтверждений и присмотра — быстро, но расходует больше "
              "лимита; песочница всё равно ограничивает этим сеансом",
    },

    # -- /auto --
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

    # -- /usage --
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
    # -- /limits, /userstats table, working-plate line, warm-cache note --
    "limits.header": {"en": "📊 <b>Your limits</b>", "ru": "📊 <b>Ваши лимиты</b>"},
    "limits.today": {"en": "Last 5h", "ru": "За 5ч"},
    "limits.week": {"en": "This week", "ru": "За неделю"},
    "limits.requests": {"en": "Requests", "ru": "Запросов"},
    "limits.no_cap": {"en": "no cap", "ru": "без лимита"},
    "limits.sessions": {"en": "Sessions: <b>{used}</b> / {cap}", "ru": "Сессии: <b>{used}</b> / {cap}"},
    "limits.unlimited_word": {"en": "∞", "ru": "∞"},
    "limits.rolling_note": {
        "en": "<i>Windows are rolling (trailing 5h / 7d, matching Anthropic's reset).</i>",
        "ru": "<i>Окна скользящие (последние 5ч / 7д, как сброс у Anthropic).</i>",
    },
    # Usage and caps are tokens (input plus output).
    "limits.account_header": {
        "en": "📊 <b>Account usage</b> (subscription, owner)",
        "ru": "📊 <b>Использование аккаунта</b> (подписка, владелец)",
    },
    "limits.account_empty": {"en": "No account usage data yet.", "ru": "Пока нет данных аккаунта."},
    "userstats.title": {"en": "User statistics", "ru": "Статистика пользователей"},
    "userstats.empty": {"en": "👥 No usage recorded yet.", "ru": "👥 Пока нет записанного использования."},
    "userstats.col_user": {"en": "User", "ru": "Пользователь"},
    "userstats.col_day": {"en": "5h", "ru": "5ч"},
    "userstats.col_week": {"en": "Week", "ru": "Неделя"},
    "userstats.col_total": {"en": "Total", "ru": "Всего"},
    "userstats.col_req": {"en": "Req", "ru": "Запр"},
    "userstats.col_last": {"en": "Last", "ru": "Актив."},
    # Tokens only (input plus output).
    "userstats.col_5h_tok": {"en": "5h tok", "ru": "5ч ток"},
    "userstats.col_wk_tok": {"en": "Wk tok", "ru": "Нед ток"},
    "userstats.col_tot_tok": {"en": "Tot tok", "ru": "Σ ток"},
    "userstats.legend": {
        "en": "tok = tokens (input + output) — the basis of the usage caps",
        "ru": "ток = токены (ввод + вывод) — по ним считаются лимиты",
    },
    "stream.usage_line": {"en": "📊 {pct}% {kind}", "ru": "📊 {pct}% {kind}"},
    "stream.kind_day": {"en": "of 5h limit", "ru": "5-часового лимита"},
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

    # -- /codesplit (owner: each code block as own message) --
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
    # -- /workingplate --
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

    # -- /stop --
    "stop.error": {
        "en": "Error while stopping: {err}",
        "ru": "Ошибка при остановке: {err}",
    },
    "stop.done": {"en": "Stopped. Queue cleared.", "ru": "Остановлено. Очередь очищена."},
    "stop.nothing": {"en": "Nothing to stop.", "ru": "Нечего останавливать."},

    # -- /whoami --
    "whoami": {
        "en": "Your id: <code>{uid}</code> · username: @{uname}",
        "ru": "Ваш id: <code>{uid}</code> · username: @{uname}",
    },

    # -- /allow /deny /users --
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
    # -- /whois (owner: user, sessions, workdir, transcript) --
    "whois.prompt": {
        "en": "🔎 Send a numeric user id to look up (or /cancel).",
        "ru": "🔎 Отправьте числовой id пользователя для поиска (или /cancel).",
    },
    "whois.bad_id": {
        "en": "Not a valid user id — send a number (e.g. <code>2859339</code>).",
        "ru": "Неверный id — отправьте число (например <code>2859339</code>).",
    },
    "whois.none": {
        "en": "No sessions found for user <code>{uid}</code>.",
        "ru": "Сессии для пользователя <code>{uid}</code> не найдены.",
    },
    "whois.head": {
        "en": "🔎 <b>User <code>{uid}</code></b>{label} — {n} session(s):",
        "ru": "🔎 <b>Пользователь <code>{uid}</code></b>{label} — сессий: {n}:",
    },
    "whois.label": {
        "en": " · level <b>{level}</b>",
        "ru": " · уровень <b>{level}</b>",
    },
    "whois.row": {
        "en": "\n{glyph} <b>{name}</b> · <code>{pubid}</code> · {status}\n   <code>{cwd}</code>",
        "ru": "\n{glyph} <b>{name}</b> · <code>{pubid}</code> · {status}\n   <code>{cwd}</code>",
    },
    "whois.tx_live": {"en": "📝 transcript", "ru": "📝 транскрипт"},
    "whois.tx_archived": {"en": "📦 archived", "ru": "📦 в архиве"},
    "whois.tx_none": {"en": "— no transcript", "ru": "— нет транскрипта"},
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
    # -- /level /expire /limit (owner access management) --
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
    # The cap is enforced in tokens (input plus output).
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
    # The list shows friendly name and @username.
    # - The numeric id is on the user card
    "users.owner_id": {"en": "👑 <b>{who}</b>", "ru": "👑 <b>{who}</b>"},
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
    # Unknown-user access request: owner notice with one-tap grant.
    "access.request_owner": {
        "en": "👤 <b>Access request</b>\n{who} (id <code>{id}</code>) tried to use the bot. Allow them?",
        "ru": "👤 <b>Запрос доступа</b>\n{who} (id <code>{id}</code>) пытается использовать бота. Разрешить?",
    },
    "access.req_allow_chat": {"en": "✅ Allow (chat)", "ru": "✅ Разрешить (чат)"},
    "access.req_allow_code": {"en": "✅ Allow (code)", "ru": "✅ Разрешить (код)"},
    "access.req_granted": {
        "en": "✅ Granted <code>{id}</code> — level <b>{level}</b>.",
        "ru": "✅ Выдан доступ <code>{id}</code> — уровень <b>{level}</b>.",
    },
    "access.req_granted_toast": {"en": "Granted — {level}", "ru": "Доступ выдан — {level}"},
    # Stale Allow tap for an already-allowed user.
    # - Level is not reset; owner is pointed to /users
    "access.req_already": {
        "en": "ℹ️ <code>{id}</code> already has <b>{level}</b> access — change it from /users.",
        "ru": "ℹ️ <code>{id}</code> уже имеет доступ <b>{level}</b> — измените его в /users.",
    },
    "access.req_already_toast": {
        "en": "Already allowed — {level}", "ru": "Уже разрешён — {level}"},
    # Expiry and caps fold into `{meta}`, shown only when limited.
    "users.entry": {
        "en": "• {who} — <b>{level}</b>{meta}",
        "ru": "• {who} — <b>{level}</b>{meta}",
    },
    "users.pending": {
        "en": "• {who} — <b>{level}</b>{meta} <i>(unpinned)</i>",
        "ru": "• {who} — <b>{level}</b>{meta} <i>(не привязан)</i>",
    },
    "users.meta_exp": {"en": " · exp: {expiry}", "ru": " · истекает: {expiry}"},
    "users.meta_caps": {"en": " · caps: {quota}", "ru": " · лимиты: {quota}"},
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

    # -- rolling rate limits and per-user effort/permissions gates --
    "access.rate_day_exceeded": {
        "en": "🔒 5-hour usage limit reached (<b>{used}/{cap}</b> tokens). It frees up as your last 5h of usage ages out.",
        "ru": "🔒 5-часовой лимит исчерпан (<b>{used}/{cap}</b> токенов). Освободится по мере устаревания последних 5 часов.",
    },
    "access.rate_week_exceeded": {
        "en": "🔒 Weekly usage limit reached (<b>{used}/{cap}</b> tokens). It frees up as your last 7 days age out.",
        "ru": "🔒 Недельный лимит исчерпан (<b>{used}/{cap}</b> токенов). Освободится по мере устаревания последних 7 дней.",
    },
    "effort.max_denied": {
        "en": "🔒 The <b>max</b> effort level is restricted (it's costly on the shared subscription). Ask the owner to grant it.",
        "ru": "🔒 Уровень <b>max</b> ограничен (дорого расходует общую подписку). Попросите владельца разрешить его.",
    },
    "perm.chat_na": {
        "en": "Permissions apply to <b>code</b> sessions only — chat's web tools are read-only and auto-approved, so there's nothing to gate here.",
        "ru": "Права применяются только к <b>код</b>-сессиям — веб-инструменты чата только для чтения и одобряются автоматически, гейтить нечего.",
    },

    # -- /users list buttons and per-user management card --
    "users.tap_hint": {
        "en": "<i>Tap a user to manage memory, limits, effort, tools, expiry, and see usage.</i>",
        "ru": "<i>Нажмите на пользователя: память, лимиты, effort, инструменты, срок доступа и статистика.</i>",
    },
    # The weighted-units usage line is retired.
    "users.entry_usage_tok": {  # per-user tokens line, NBSP-padded columns
        "en": "<code>↳ tokens: 5h {day} · wk {week} · tot {total}</code>",
        "ru": "<code>↳ ток.: 5ч {day} · нед {week} · всего {total}</code>",
    },
    "users.btn_owner": {"en": "👑 You (owner)", "ru": "👑 Вы (владелец)"},
    "users.btn_owner_bare": {"en": "Owner", "ru": "Владелец"},  # owner label fallback
    "users.btn_add": {"en": "➕ Add user", "ru": "➕ Добавить"},
    "users.btn_stats": {"en": "📊 Statistics", "ru": "📊 Статистика"},
    "users.btn_entry": {"en": "{who} · {level}", "ru": "{who} · {level}"},
    "users.btn_pending": {"en": "{who} · {level} (unpinned)", "ru": "{who} · {level} (не привязан)"},
    "usercard.title": {
        # `{who}` is an HTML link built and escaped in handlers.
        # - No `<code>` wrapper, it would break the link
        # - Title is sent without re-escaping
        "en": "<b>User</b> {who} {kind}",
        "ru": "<b>Пользователь</b> {who} {kind}",
    },
    "usercard.kind_owner": {"en": "(owner)", "ru": "(владелец)"},
    "usercard.kind_pending": {"en": "(unpinned)", "ru": "(не привязан)"},
    "usercard.level": {"en": "Level: <b>{level}</b>", "ru": "Уровень: <b>{level}</b>"},
    "usercard.expiry": {"en": "Access expires: <b>{expiry}</b>", "ru": "Доступ истекает: <b>{expiry}</b>"},
    "usercard.rate": {
        "en": "Limits: 5h <b>{day}</b> · week <b>{week}</b>",
        "ru": "Лимиты: 5ч <b>{day}</b> · неделя <b>{week}</b>",
    },
    "usercard.memory": {"en": "Global memory: <b>{state}</b>", "ru": "Глобальная память: <b>{state}</b>"},
    "usercard.maxeffort": {"en": "Max effort allowed: <b>{state}</b>", "ru": "Разрешён max effort: <b>{state}</b>"},
    "usercard.tools": {"en": "Tools allowed: <b>{tools}</b>", "ru": "Разрешено инструментов: <b>{tools}</b>"},
    "usercard.cap_all": {"en": "all", "ru": "все"},
    "usercard.usage": {
        "en": "Units: 5h <b>{day}</b> · week <b>{week}</b> · total <b>{total}</b> ({reqs} req)",
        "ru": "Единицы: 5ч <b>{day}</b> · неделя <b>{week}</b> · всего <b>{total}</b> ({reqs} зап.)",
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
    "usercard.btn_level": {"en": "Level: {level} ▸", "ru": "Уровень: {level} ▸"},  # opens picker
    # File cabinet emoji means memory/context; brain is for MODEL.
    "usercard.btn_memory": {"en": "🗄 Memory: {state}", "ru": "🗄 Память: {state}"},
    "usercard.btn_maxeffort": {"en": "⚡ Max effort: {state}", "ru": "⚡ Max effort: {state}"},
    "usercard.pick_memory": {"en": "🗄 Global memory", "ru": "🗄 Глобальная память"},
    "usercard.pick_maxeffort": {"en": "⚡ Max effort", "ru": "⚡ Max effort"},
    "usercard.pick_level": {"en": "Access level", "ru": "Уровень доступа"},
    "usercard.btn_tools": {"en": "🧰 Tools: {val}", "ru": "🧰 Инструменты: {val}"},
    # Per-user access exceptions.
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
    "usercard.btn_day": {"en": "📊 5h limit…", "ru": "📊 Лимит/5ч…"},
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
    # Caps are compared against tokens (input plus output).
    # - The short window is 5h, matching Anthropic's reset
    "usercard.prompt_day": {
        "en": "Send the 5-HOUR usage cap in <b>tokens</b> (input + output; e.g. <code>500k</code>, or <code>off</code>; /cancel).",
        "ru": "Отправьте 5-ЧАСОВОЙ лимит в <b>токенах</b> (ввод + вывод; напр. <code>500k</code>, или <code>off</code>; /cancel).",
    },
    "usercard.prompt_week": {
        "en": "Send the WEEKLY usage cap in <b>tokens</b> (input + output; e.g. <code>2m</code>, or <code>off</code>; /cancel).",
        "ru": "Отправьте НЕДЕЛЬНЫЙ лимит в <b>токенах</b> (ввод + вывод; напр. <code>2m</code>, или <code>off</code>; /cancel).",
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
        "en": "Tokens — 5h <b>{day}</b> · week <b>{week}</b> · total <b>{total}</b>",
        "ru": "Токены — 5ч <b>{day}</b> · неделя <b>{week}</b> · всего <b>{total}</b>",
    },
    "whoami.caps": {"en": "Limits: <b>{caps}</b>", "ru": "Лимиты: <b>{caps}</b>"},

    # -- /status --
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
    "status.busy": {
        "en": "Busy: {busy}; queued: {queued}",
        "ru": "Занят: {busy}; в очереди: {queued}",
    },
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
    # /status fallback labels when the multi-window block is empty.
    "status.rate_type": {"en": "type: {val}", "ru": "тип: {val}"},
    "status.rate_status": {"en": "status: {val}", "ru": "статус: {val}"},
    "status.rate_util": {"en": "utilization: {val}%", "ru": "загрузка: {val}%"},
    "status.rate_resets": {"en": "resets: {val}", "ru": "сброс: {val}"},

    # -- /context --
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

    # -- /recap, /history --
    # - Model-facing recap instruction, localized to the UI language
    "recap.prompt": {
        "en": "Recap our conversation so far in one short sentence.",
        "ru": "Кратко изложи нашу беседу одним коротким предложением.",
    },
    "recap.empty": {
        "en": "No conversation logged yet in this session.",
        "ru": "В этой сессии ещё нет записанного разговора.",
    },
    # /recap with no logged turns skips the model call.
    # - The earlier chat is likely a separate session
    "recap.empty_session": {
        "en": "🆕 Nothing to recap — this session has no earlier messages. After a long idle "
              "gap a fresh session starts automatically, so your previous conversation is "
              "kept as a separate entry: open /sessions to switch back to it.",
        "ru": "🆕 Нечего пересказывать — в этой сессии ещё нет сообщений. После долгого "
              "простоя автоматически начинается новая сессия, поэтому предыдущий разговор "
              "сохранён отдельно: откройте /sessions, чтобы вернуться к нему.",
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

    # -- /stream --
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

    # -- /close and topic errors --
    # - Supergroup and forum-topic support is paused
    # - Rich-draft streaming fails there with `TEXTDRAFT_PEER_INVALID`
    "topic.disabled": {
        "en": "🚧 Group (forum-topic) sessions are paused for now — please use this bot in a "
              "direct message (DM). Rich streaming isn't supported in supergroups yet.",
        "ru": "🚧 Сессии в группах (темах форума) пока приостановлены — пользуйтесь ботом в "
              "личных сообщениях (DM). Богатый стриминг в супергруппах пока не поддерживается.",
    },
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

    # -- /queue --
    # - A message sent mid-reply goes into the running reply
    # - The ack only covers the pre-client fallback
    # - Waiting behind a running reply is silent
    "queue.full_reject": {
        "en": "⚠️ Too many queued ({n} max). Wait for the current reply, or /stop to interrupt.",
        "ru": "⚠️ Слишком много в очереди (макс. {n}). Дождитесь ответа или /stop, чтобы прервать.",
    },
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

    # -- stop button and control message --
    "stopbtn.stopping": {"en": "Stopping…", "ru": "Останавливаю…"},
    "stopbtn.nothing": {"en": "Nothing is running.", "ru": "Ничего не выполняется."},
    "stream.working": {"en": "⏳ <i>Working…</i>", "ru": "⏳ <i>Работаю…</i>"},
    # Localized animated thinking placeholder and tool-phase labels.
    # - `thinking_words` is a comma-separated rotation list
    # - Verbs feed `tool_phase_label`; emoji stays in code
    "stream.thinking": {"en": "Thinking", "ru": "Думаю"},
    "stream.thinking_words": {
        # Keep en and ru at the same count (30).
        # - `test_i18n` enforces parity
        "en": "Thinking,Pondering,Ruminating,Cogitating,Mulling,Noodling,Percolating,"
              "Marinating,Deliberating,Contemplating,Brewing,Churning,Synthesizing,"
              "Reasoning,Considering,Puzzling,Untangling,Reflecting,Weighing,Analyzing,"
              "Reckoning,Musing,Processing,Unpacking,Calculating,Figuring,Wrangling,"
              "Scheming,Computing,Deducing",
        "ru": "Думаю,Размышляю,Соображаю,Обдумываю,Прикидываю,Анализирую,Рассуждаю,"
              "Взвешиваю,Кумекаю,Вникаю,Обмозговываю,Осмысляю,Прорабатываю,Мозгую,"
              "Систематизирую,Синтезирую,Распутываю,Вычисляю,Продумываю,Соотношу,"
              "Перевариваю,Усваиваю,Распаковываю,Углубляюсь,Разбираюсь,Прокручиваю,"
              "Концентрируюсь,Изучаю,Рефлексирую,Структурирую",
    },
    # Search-themed gerunds for the thinking tag during web search.
    # - Same count en/ru; `test_i18n` enforces parity
    "stream.searching_words": {
        "en": "Searching,Looking it up,Digging,Researching,Gathering sources,Scanning,"
              "Browsing,Cross-checking,Fact-finding,Combing the web,Tracking it down,"
              "Sourcing,Surveying,Checking sources,Hunting,Sifting",
        "ru": "Ищу,Гуглю,Копаю,Изучаю,Собираю источники,Сканирую,Просматриваю,Сверяю,"
              "Уточняю,Прочёсываю сеть,Выясняю,Разыскиваю,Проверяю источники,Сопоставляю,"
              "Отыскиваю,Перебираю",
    },
    "stream.verb_reading": {"en": "Reading", "ru": "Читаю"},
    "stream.verb_writing": {"en": "Writing", "ru": "Пишу"},
    "stream.verb_editing": {"en": "Editing", "ru": "Редактирую"},
    "stream.verb_searching_code": {"en": "Searching code", "ru": "Ищу в коде"},
    "stream.verb_finding_files": {"en": "Finding files", "ru": "Ищу файлы"},
    "stream.verb_listing": {"en": "Listing files", "ru": "Смотрю файлы"},
    "stream.verb_web_search": {"en": "Searching the web", "ru": "Ищу в вебе"},
    "stream.verb_web_fetch": {"en": "Reading a page", "ru": "Читаю страницу"},
    "stream.verb_planning": {"en": "Planning", "ru": "Планирую"},
    "stream.verb_running": {"en": "Running", "ru": "Выполняю"},
    "stream.phase_running_any": {"en": "Running a command", "ru": "Выполняю команду"},
    # Live web-research card.
    # - In-progress header while searching, done header after the turn
    # - One resource per line
    "stream.searching": {"en": "🔎 Searching the web…", "ru": "🔎 Ищу в вебе…"},
    "stream.sources_title": {"en": "📚 Sources", "ru": "📚 Источники"},
    "stream.too_long": {
        "en": "📄 Response too long — sent as a file.",
        "ru": "📄 Ответ слишком длинный — отправлен файлом.",
    },
    # A table over 20 columns is sent as PNG.
    # - This plain-text note replaces it in the markdown body
    "stream.wide_table": {
        "en": "📊 Table {n} ({cols} columns) — too wide to display inline; sent as an image below.",
        "ru": "📊 Таблица {n} ({cols} столбцов) — слишком широкая для встроенного показа; отправлена изображением ниже.",
    },
    # A reply's SVG diagram is rasterized, sent as photo.
    # - The note marks its spot
    # - `svg_rendering` is the draft placeholder
    "stream.svg_image": {
        "en": "🖼 Diagram — sent as an image below.",
        "ru": "🖼 Схема — отправлена изображением ниже.",
    },
    "stream.svg_rendering": {"en": "🖼 Rendering a diagram…", "ru": "🖼 Рисую схему…"},
    # A fenced location block becomes a real Telegram map pin.
    # - This note marks where it was
    "stream.location": {
        "en": "📍 Location — sent on the map below.",
        "ru": "📍 Локация — отправлена на карте ниже.",
    },
    # Inbound location: a shared pin becomes a model turn.
    # - Plain text, not shown to the user
    # - Localized like `voice.model_note`
    "location.model_note": {
        "en": "[The user shared a location from Telegram. "
              "Coordinates: latitude {lat}, longitude {lon}.]",
        "ru": "[Пользователь отправил геопозицию из Telegram. "
              "Координаты: широта {lat}, долгота {lon}.]",
    },
    "location.venue_model_note": {
        "en": "[The user shared a place from Telegram: {title} — {address}. "
              "Coordinates: latitude {lat}, longitude {lon}.]",
        "ru": "[Пользователь отправил место из Telegram: {title} — {address}. "
              "Координаты: широта {lat}, долгота {lon}.]",
    },
    # Header of the live task-list card: total, completed, not done.
    "todo.card_header": {
        "en": "📋 {n} tasks ({done} done, {open} open)",
        "ru": "📋 {n} задач ({done} готово, {open} осталось)",
    },
    # Recurring scheduled prompts.
    "schedule.usage": {
        "en": "⏰ <b>Schedule a recurring prompt</b>\nFormat: <code>/schedule &lt;when&gt; | &lt;prompt&gt;</code>\n"
              "Examples:\n• <code>/schedule every day at 9:00 | summarize my GitHub notifications</code>\n"
              "• <code>/schedule every monday at 18:00 | weekly review</code>\n"
              "• <code>/schedule every 2 hours | check the deploy status</code>\n"
              "Times use the server clock. See your schedules with /schedules.",
        "ru": "⏰ <b>Запланировать повторяющийся запрос</b>\nФормат: <code>/schedule &lt;когда&gt; | &lt;запрос&gt;</code>\n"
              "Примеры:\n• <code>/schedule every day at 9:00 | сводка по GitHub-уведомлениям</code>\n"
              "• <code>/schedule every monday at 18:00 | недельный обзор</code>\n"
              "• <code>/schedule every 2 hours | проверь статус деплоя</code>\n"
              "Время — по часам сервера. Список — /schedules.",
    },
    "schedule.parse_error": {
        "en": "⚠️ Could not read that schedule: {err}\nTry /schedule for the format.",
        "ru": "⚠️ Не удалось разобрать расписание: {err}\nФормат — /schedule.",
    },
    "schedule.created": {
        "en": "✅ Scheduled <b>{when}</b> — next run {next}.\nManage with /schedules.",
        "ru": "✅ Запланировано <b>{when}</b> — следующий запуск {next}.\nУправление — /schedules.",
    },
    "schedule.cap_reached": {
        "en": "⚠️ You already have {n} schedules (the max). Delete one with /schedules first.",
        "ru": "⚠️ У вас уже {n} расписаний (максимум). Сначала удалите одно через /schedules.",
    },
    "schedule.list_empty": {
        "en": "⏰ No schedules yet. Create one with /schedule.",
        "ru": "⏰ Расписаний пока нет. Создайте через /schedule.",
    },
    "schedule.list_header": {
        "en": "⏰ <b>Your schedules</b> ({n}/{cap}):",
        "ru": "⏰ <b>Ваши расписания</b> ({n}/{cap}):",
    },
    "schedule.list_item": {
        "en": "{state} <b>{when}</b> — next {next}\n   <i>{prompt}</i>",
        "ru": "{state} <b>{when}</b> — далее {next}\n   <i>{prompt}</i>",
    },
    "schedule.run_notice": {
        "en": "⏰ <i>Running scheduled task:</i> {prompt}",
        "ru": "⏰ <i>Выполняю запланированную задачу:</i> {prompt}",
    },
    "schedule.deleted": {"en": "🗑 Schedule deleted.", "ru": "🗑 Расписание удалено."},
    "schedule.paused": {"en": "⏸ Schedule paused.", "ru": "⏸ Расписание приостановлено."},
    "schedule.resumed": {"en": "▶️ Schedule resumed.", "ru": "▶️ Расписание возобновлено."},
    "schedule.prompt": {
        "en": "Send the schedule as <code>&lt;when&gt; | &lt;prompt&gt;</code> (or /cancel).",
        "ru": "Пришлите расписание как <code>&lt;когда&gt; | &lt;запрос&gt;</code> (или /cancel).",
    },
    "btn.sched_pause": {"en": "⏸ Pause", "ru": "⏸ Пауза"},
    "btn.sched_resume": {"en": "▶️ Resume", "ru": "▶️ Возобновить"},
    "btn.sched_delete": {"en": "🗑 Delete", "ru": "🗑 Удалить"},

    # -- /retry --
    "retry.error": {
        "en": "Could not retry: <code>{err}</code>",
        "ru": "Не удалось повторить: <code>{err}</code>",
    },
    "retry.ok": {"en": "Re-running the last prompt.", "ru": "Повторяю последний запрос."},
    "retry.nothing": {"en": "Nothing to retry yet.", "ru": "Пока нечего повторять."},

    # -- text and attachments --
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
    # Outbox file send-back notices.
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
    # Appended when an album exceeded the per-turn item cap.
    "attach.album_dropped": {
        "en": "[{n} more file(s) in this album were skipped — over the limit]",
        "ru": "[ещё {n} файл(ов) из этого альбома пропущено — превышен лимит]",
    },

    # -- voice notes --
    "voice.transcribing": {"en": "🎙 Transcribing…", "ru": "🎙 Расшифровываю…"},
    "voice.transcript_prefix": {"en": "🎙 <i>{text}</i>", "ru": "🎙 <i>{text}</i>"},
    # Prepended to the transcript sent to the model.
    # - Hidden from the user
    # - Tells the agent it was a voice note
    "voice.model_note": {
        "en": "[Voice message — automatic transcription below; it may contain "
              "speech-recognition errors, so interpret it by intent.]\n\n{text}",
        "ru": "[Голосовое сообщение — ниже автоматическая расшифровка; возможны ошибки "
              "распознавания речи, понимай по смыслу.]\n\n{text}",
    },
    "voice.too_long": {
        "en": "🎙 Voice message is too long (max {sec}s).",
        "ru": "🎙 Голосовое сообщение слишком длинное (макс. {sec} с).",
    },
    "voice.transcribe_failed": {
        "en": "🎙 Could not transcribe the voice message.",
        "ru": "🎙 Не удалось расшифровать голосовое сообщение.",
    },
    "voice.disabled": {
        "en": "🎙 Voice transcription is unavailable (missing ffmpeg or the speech model).",
        "ru": "🎙 Расшифровка голоса недоступна (нет ffmpeg или модели распознавания).",
    },

    # -- permission gate --
    "permgate.allow_btn": {"en": "✅ Allow", "ru": "✅ Разрешить"},
    "permgate.deny_btn": {"en": "⛔ Deny", "ru": "⛔ Запретить"},
    "permgate.request": {
        "en": "🔐 Permission request: <b>{tool}</b>",
        "ru": "🔐 Запрос разрешения: <b>{tool}</b>",
    },
    "permgate.run_q": {"en": "Run this tool?", "ru": "Запустить этот инструмент?"},
    # Shown when a prompt is relayed to the owner.
    "permgate.for_user": {
        "en": "👤 Session owner: <code>{uid}</code>",
        "ru": "👤 Владелец сессии: <code>{uid}</code>",
    },
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

    # -- session manager notices --
    "session.not_initialized": {
        "en": "⚠️ Session not initialized.",
        "ru": "⚠️ Сессия не инициализирована.",
    },
    "session.unknown_error": {"en": "Unknown error.", "ru": "Неизвестная ошибка."},
    "session.internal_error": {
        "en": "⚠️ Internal error: {exc}",
        "ru": "⚠️ Внутренняя ошибка: {exc}",
    },
    # Owner-only heads-up above a reply before the host login expires.
    # - Plain text; rides the markdown render path
    "session.login_expiry_warn": {
        "en": "⚠️ Server login expires in {days}d — re-login on the host with the claude CLI to avoid downtime.",
        "ru": "⚠️ Логин на сервере истекает через {days}д — перелогинься на хосте через claude CLI, чтобы не было простоя.",
    },
    # Pushed to the owner when token refresh keeps failing.
    # - The login died early (revoked or rotated)
    # - Until fixed, every turn fails with a server-side error
    "session.login_refresh_failed": {
        "en": "🔴 Server login is not refreshing ({status}, {fails} in a row). Turns will fail "
              "with a \"server-side error\" until you re-login on the host "
              "(claude setup-token) and restart the service.",
        "ru": "🔴 Логин на сервере не обновляется ({status}, {fails} подряд). Запросы будут "
              "падать с «ошибкой на стороне сервера», пока не перелогинишься на хосте "
              "(claude setup-token) и не перезапустишь сервис.",
    },
    "session.login_refresh_recovered": {
        "en": "🟢 Server login is refreshing again.",
        "ru": "🟢 Логин на сервере снова обновляется.",
    },
    "busy.queued": {
        "en": "⏳ Server busy — your turn is queued and will run as soon as a slot frees up.",
        "ru": "⏳ Сервер занят — ваш ход в очереди и начнётся, как только освободится слот.",
    },

    # -- engine error events (stable `error_key`) --
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
    # A model refusal arrives as invalid_request; the engine relabels it.
    # - Distinct keys avoid the misleading "Invalid request" message
    # - A cyber-safeguard refusal gets its own message
    "err.cyber_refusal": {
        "en": "The model declined this turn under its cybersecurity safeguards — a "
              "safety refusal, not a bug or a malformed request. Try a new session "
              "(/new) with a narrower, factual question, or switch model (/model).",
        "ru": "Модель отклонила этот запрос из-за защиты по теме кибербезопасности — "
              "это отказ по соображениям безопасности, а не ошибка запроса. Начните "
              "новую сессию (/new) с более узким, фактическим вопросом или смените "
              "модель (/model).",
    },
    "err.model_refusal": {
        "en": "The model declined to answer this turn (a safety refusal). Try "
              "rephrasing in a new session (/new), or switch model (/model).",
        "ru": "Модель отказалась отвечать на этот запрос (отказ по соображениям "
              "безопасности). Переформулируйте в новой сессии (/new) или смените "
              "модель (/model).",
    },
    "err.server_error": {
        "en": "Server-side error. Please try again.",
        "ru": "Ошибка на стороне сервера. Попробуйте ещё раз.",
    },
    # Time-to-first-token watchdog message, when the service emits nothing in time.
    # - Avoids an endless thinking animation during silent CLI retries
    "err.service_unavailable": {
        "en": "The service is taking too long to respond — it may be temporarily "
              "overloaded or unavailable. Please try again.",
        "ru": "Сервис слишком долго не отвечает — возможно, он временно перегружен "
              "или недоступен. Попробуйте ещё раз.",
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

    # -- usage windows --
    "usage.status.ok": {"en": "OK", "ru": "OK"},
    "usage.status.high": {"en": "⚠ high", "ru": "⚠ высокое"},
    "usage.status.limited": {"en": "⛔ limited", "ru": "⛔ лимит"},
    # Neutral marker for a present but unrecognized window status.
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
    # Window labels; model names stay English, only "overage" differs.
    "usage.label.overage": {"en": "overage", "ru": "перерасход"},

    # -- command-menu descriptions --
    # - Menu descriptions live in the commands registry labels
    # - Edit `Cmd.label` there, not here
}


def t(key: str, lang: str = DEFAULT_LANG, /, **kwargs) -> str:
    """Look up `key` for a locale and format with `kwargs`.

    - `lang` is positional-only so `{lang}` can be a kwarg
    - Falls back to English, then to the raw key
    - HTML tags and placeholders must match across columns
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


# Small display helpers: on/off, yes/no, mode word.
def onoff(value: bool, lang: str = DEFAULT_LANG) -> str:
    """Localized on/off for a boolean."""
    return t("common.on", lang) if value else t("common.off", lang)


def yesno(value: bool, lang: str = DEFAULT_LANG) -> str:
    """Localized yes/no for a boolean."""
    return t("common.yes", lang) if value else t("common.no", lang)


def mode_word(mode: str, lang: str = DEFAULT_LANG) -> str:
    """Localized session-type word for display."""
    return t("mode.word_code" if mode == "code" else "mode.word_chat", lang)


def maybe_t(key: str, lang: str = DEFAULT_LANG, fallback: str = "", /, **kwargs) -> str:
    """Translate `key` if the catalog has it, else `fallback`.

    - For names that come from outside the bot
    """
    return t(key, lang, **kwargs) if key in CATALOG else fallback


def placeholder_session_names() -> set[str]:
    """Every name an untitled session may carry, in all locales.

    - Includes legacy defaults so the untitled sweep recognizes them
    """
    out: set[str] = set()
    for key in ("session.default_name_chat", "session.default_name_code",
                "session.first_default"):
        out.update(v.strip() for v in CATALOG.get(key, {}).values() if v.strip())
    for v in CATALOG.get("session.legacy_default_names", {}).values():
        out.update(x.strip() for x in v.split("|") if x.strip())
    return out


def lang_name(lang: str) -> str:
    """Display name of a locale, or the code if unknown."""
    return LANGUAGES.get(lang, lang)
