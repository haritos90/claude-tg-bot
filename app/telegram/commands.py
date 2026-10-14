"""Single source of truth for the bot's Telegram commands.

- Each command is one `Cmd` row here
- `handlers.py` derives menu lists and descriptions from `COMMANDS`
- Labels (en+ru) live here; /help prose stays in `i18n.py`
- `assert_commands_consistent` fails loudly on registry drift
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Cmd:
    """One Telegram command, defined once for every surface.

    - `slug`: primary command word without the slash
    - `aliases`: extra words for same handler, not in menu
    - `scope`: `all`, `code`, or `owner`
    - `in_menu`: whether it appears in the setMyCommands menu
    - `label`: en/ru menu description dict
    """

    slug: str
    label: dict[str, str]
    scope: str = "all"
    in_menu: bool = True
    aliases: tuple[str, ...] = ()
    help_group: str = ""


# One row per real command; list order is menu order.
# - Frequency-ranked: everyday commands first, rare ones scroll below
# - Telegram surfaces only about the top 5 on mobile
# - Retired /stop and /stream are omitted entirely
# - `code`/`owner` scope rows feed per-user menus
COMMANDS: tuple[Cmd, ...] = (
    # Tier A: everyday (top of the menu)
    Cmd("new", {"en": "➕ New session (starts as chat)",
                "ru": "➕ Новая сессия (создаётся как чат)"}, help_group="sessions"),
    Cmd("sessions", {"en": "Browse / switch / delete sessions",
                     "ru": "Обзор / переключение / удаление сессий"}, help_group="sessions"),
    Cmd("settings", {"en": "Open the settings menu",
                     "ru": "Открыть меню настроек"}, help_group="settings"),
    # Tier B: common run control and type switch
    Cmd("code", {"en": "🟩 Upgrade this session to code",
                 "ru": "🟩 Повысить сессию до кода"}, scope="code", help_group="code"),
    Cmd("chat", {"en": "💬 Downgrade this session to chat",
                 "ru": "💬 Понизить сессию до чата"}, help_group="code"),
    Cmd("clear", {"en": "Clear the session context",
                  "ru": "Очистить контекст сессии"}, aliases=("reset",), help_group="sessions"),
    Cmd("retry", {"en": "Re-run the last prompt",
                  "ru": "Повторить последний запрос"}, help_group="run"),
    Cmd("status", {"en": "Current session info",
                   "ru": "Сведения о текущей сессии"}, help_group="sessions"),
    Cmd("schedule", {"en": "⏰ Schedule a recurring prompt",
                     "ru": "⏰ Запланировать повторяющийся запрос"}, help_group="run"),
    Cmd("schedules", {"en": "List / pause / delete schedules",
                      "ru": "Список / пауза / удаление расписаний"}, help_group="run"),
    # Tier C: occasional settings (pickers and toggles)
    # - Model and effort names come from the CLI, not here
    Cmd("model", {"en": "Switch model",
                  "ru": "Сменить модель"}, help_group="settings"),
    Cmd("effort", {"en": "Reasoning depth",
                   "ru": "Глубина рассуждений"}, help_group="settings"),
    # The `/memory` command is retired; 1M is the native window.
    Cmd("forget", {"en": "Clear this topic's agent-saved memory (code)",
                   "ru": "Очистить память темы, сохранённую агентом (код)"},
        scope="code", help_group="settings"),  # session memory is code-only
    Cmd("language", {"en": "Choose the interface language",
                     "ru": "Выбрать язык интерфейса"}, help_group="settings"),
    # Tier C: occasional run and session content
    Cmd("context", {"en": "Context-window usage",
                    "ru": "Использование окна контекста"}, help_group="run"),
    Cmd("limits", {"en": "📊 Your usage limits",
                   "ru": "📊 Ваши лимиты использования"}, help_group="run"),
    # No queue: messages sent mid-reply go into the running turn.
    Cmd("rename", {"en": "Rename the current session",
                   "ru": "Переименовать текущую сессию"}, help_group="sessions"),
    Cmd("recap", {"en": "📋 One-line AI recap of the session",
                  "ru": "📋 Краткая сводка сессии от ИИ (одна строка)"}, help_group="sessions"),
    Cmd("last", {"en": "Show the last exchange (verbatim)",
                 "ru": "Показать последний обмен (дословно)"}, help_group="sessions"),
    Cmd("history", {"en": "📄 Export the full transcript (file)",
                    "ru": "📄 Выгрузить полную расшифровку (файл)"}, help_group="sessions"),
    Cmd("fork", {"en": "Branch this session into a new one",
                 "ru": "Ответвить эту сессию в новую"}, help_group="sessions"),
    # Tier D: code-only
    Cmd("files", {"en": "Browse the working-dir tree (code)",
                  "ru": "Дерево рабочей папки (код)"}, scope="code", help_group="code"),
    Cmd("export", {"en": "Export working-dir files as .zip (code)",
                   "ru": "Экспорт файлов рабочей папки (.zip, код)"}, scope="code", help_group="code"),
    Cmd("maxturns", {"en": "Cap agentic turns (code)",
                     "ru": "Лимит агентных ходов (код)"}, scope="code", help_group="code"),
    # Routine code-session config surfaced in the menu.
    Cmd("permissions", {"en": "Code tool policy: auto-edits · plan · full-access",
                        "ru": "Политика инструментов кода: auto-edits · plan · full-access"},
        scope="code", help_group="code"),
    Cmd("tools", {"en": "Configure this session's tools",
                  "ru": "Настроить инструменты сессии"},
        scope="code", help_group="code"),
    Cmd("secret", {"en": "🔐 Set a per-session service credential (code)",
                   "ru": "🔐 Учётные данные сервиса для сессии (код)"},
        scope="code", help_group="code"),
    Cmd("shell", {"en": "⌨️ Toggle shell mode — run commands in the jail (code)",
                  "ru": "⌨️ Режим shell — команды в песочнице (код)"},
        scope="code", help_group="code"),
    # Tier E: meta
    Cmd("help", {"en": "Show help", "ru": "Показать справку"}, help_group="meta"),
    Cmd("whoami", {"en": "Show your id and username",
                   "ru": "Показать ваш id и username"}, help_group="meta"),

    # Tier E: secondary handlers kept out of the menu.
    # - Typeable, or reached via inline menus
    # - `scope="code"` keeps per-user menu derivation honest
    Cmd("usage", {"en": "Subscription-usage display",
                  "ru": "Показ использования подписки"},
        in_menu=False, help_group="settings"),
    Cmd("cancel", {"en": "Cancel a pending prompt-capture",
                   "ru": "Отменить ввод аргумента"},
        in_menu=False, help_group="meta"),
    Cmd("newchat", {"en": "💬 New chat session", "ru": "💬 Новая чат-сессия"},
        in_menu=False, help_group="sessions"),
    Cmd("newcode", {"en": "🟩 New code session", "ru": "🟩 Новая код-сессия"},
        scope="code", in_menu=False, help_group="sessions"),
    Cmd("mode", {"en": "Switch session type (alias of /code, /chat)",
                 "ru": "Сменить тип сессии (синоним /code, /chat)"},
        in_menu=False, help_group="code"),
    Cmd("close", {"en": "Close (delete) the current session",
                  "ru": "Закрыть (удалить) текущую сессию"},
        in_menu=False, help_group="sessions"),

    # Tier F: owner-only admin commands (`scope="owner"`).
    # - Appended after the shared list in owner's private chat
    # - `in_menu=False` keeps them out of the shared menu
    # - Order: users first
    Cmd("users", {"en": "List allowed users (owner)", "ru": "Список пользователей (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("userstats", {"en": "📊 User usage stats — table (owner)",
                      "ru": "📊 Статистика пользователей — таблица (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("whois", {"en": "🔎 A user's sessions → workdir → transcript (owner)",
                  "ru": "🔎 Сессии пользователя → каталог → транскрипт (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("allow", {"en": "Allow a user (owner)", "ru": "Разрешить пользователя (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("deny", {"en": "Remove a user (owner)", "ru": "Удалить пользователя (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("level", {"en": "Set a user's access level (owner)", "ru": "Уровень доступа (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("expire", {"en": "Set a user's access expiry (owner)", "ru": "Срок доступа (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("limit", {"en": "Top up a user's token grant (owner)", "ru": "Пополнить лимит токенов (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("auto", {"en": "Run code tools without asking (owner)",
                 "ru": "Запускать инструменты кода без вопросов (владелец)"},
        scope="owner", in_menu=False, help_group="owner"),
    Cmd("codesplit", {"en": "Code blocks as separate messages: on | off (owner)",
                      "ru": "Блоки кода отдельными сообщениями: on | off (владелец)"},
        scope="owner", in_menu=False, help_group="settings"),
    Cmd("workingplate", {"en": "⏳ Working/Stop plate: on | off (owner)",
                         "ru": "⏳ Плашка Working/Stop: on | off (владелец)"},
        scope="owner", in_menu=False, help_group="settings"),
    # Owner-only streaming self-test is typeable only.
    # - Not advertised in the menu or /help
    # - Kept last
    Cmd("test", {"en": "Simulate a streamed reply (owner self-test)",
                 "ru": "Симуляция потоковой генерации (тест владельца)"},
        scope="owner", in_menu=False, help_group=""),
)

# Locales every `Cmd.label` must cover.
# - Hard-coded to avoid an import cycle with `i18n`
# - Startup assertion re-checks against `i18n.LANGUAGES`
REQUIRED_LOCALES: tuple[str, ...] = ("en", "ru")


def by_slug() -> dict[str, Cmd]:
    """Map slug to `Cmd` for quick lookup."""
    return {c.slug: c for c in COMMANDS}


def menu_slugs() -> list[str]:
    """In-menu command slugs, in registry order."""
    return [c.slug for c in COMMANDS if c.in_menu]


def code_slugs() -> list[str]:
    """Code-only command slugs."""
    return [c.slug for c in COMMANDS if c.scope == "code"]


def owner_slugs() -> list[str]:
    """Owner-only command slugs."""
    return [c.slug for c in COMMANDS if c.scope == "owner"]


def all_command_words() -> set[str]:
    """Every word that should have a handler: slugs + aliases."""
    words: set[str] = set()
    for c in COMMANDS:
        words.add(c.slug)
        words.update(c.aliases)
    return words


# Handler/registry exceptions: slugs with a handler but no `Cmd` row.
# - /sandbox keeps a courtesy handler but no registry row
# - Without this exception the drift check aborts startup setup
_HANDLER_EXCEPTIONS: frozenset[str] = frozenset({"sandbox"})


def registered_handler_slugs(handlers_path: str | Path | None = None) -> set[str]:
    """Scan `handlers.py` for command words with a live handler.

    - Only uncommented `@router.message(Command(...))` count
    - `CommandStart` is ignored; /start has no menu entry
    - Returns every slug and alias with a handler
    """
    path = Path(handlers_path) if handlers_path else Path(__file__).with_name("handlers.py")
    src = path.read_text(encoding="utf-8")
    words: set[str] = set()
    pat = re.compile(r'Command\(\s*((?:"[^"]+"\s*,?\s*)+)\)')
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue  # skip commented-out handlers
        for m in pat.finditer(line):
            for w in re.findall(r'"([^"]+)"', m.group(1)):
                words.add(w)
    return words


def assert_commands_consistent(handlers_path: str | Path | None = None,
                               languages: tuple[str, ...] | None = None) -> None:
    """Raise ValueError if the command surfaces have drifted.

    - Every label covers every required locale
    - Scope is one of the allowed values
    - Live handler words and `Cmd` words match both ways
    - Called from `setup_commands` at startup
    """
    locales = tuple(languages) if languages else REQUIRED_LOCALES
    problems: list[str] = []

    # Check labels and scope.
    seen_slugs: set[str] = set()
    for c in COMMANDS:
        if c.slug in seen_slugs:
            problems.append(f"duplicate Cmd slug: {c.slug!r}")
        seen_slugs.add(c.slug)
        if c.scope not in ("all", "code", "owner"):
            problems.append(f"/{c.slug}: invalid scope {c.scope!r}")
        for loc in ("en", "ru", *locales):
            if loc not in c.label or not c.label[loc]:
                problems.append(f"/{c.slug}: label missing locale {loc!r}")

    # Check handler and registry parity.
    handler_words = registered_handler_slugs(handlers_path)
    registry_words = all_command_words()
    # Control words like /start are handlers, not commands.
    # - `CommandStart` is not matched; only `Command(...)` words appear
    missing_rows = handler_words - registry_words - _HANDLER_EXCEPTIONS
    missing_handlers = registry_words - handler_words - _HANDLER_EXCEPTIONS
    for w in sorted(missing_rows):
        problems.append(f"/{w}: has a @router handler but no Cmd row")
    for w in sorted(missing_handlers):
        problems.append(f"/{w}: has a Cmd row but no live @router handler")

    if problems:
        raise ValueError(
            "command registry drift — fix commands.py / handlers.py:\n  "
            + "\n  ".join(problems)
        )
