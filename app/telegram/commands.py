"""Single source of truth for the bot's Telegram commands (#139).

Before this, command names + menu descriptions lived in FOUR hand-synced places
that drifted: ``_COMMAND_NAMES`` / ``_CODE_COMMAND_NAMES`` / ``_OWNER_COMMAND_NAMES``
in handlers.py, the ``cmd.<slug>`` rows in i18n.py, and the /help prose. This
module reconciles them: every real command is ONE :class:`Cmd` row here, and
handlers.py derives its menu lists + setMyCommands descriptions from ``COMMANDS``.

The menu DESCRIPTION (label) is now owned here (en+ru), so a command name +
one-liner is defined exactly once per language. The /help prose still lives in
i18n.py (too much surrounding narrative to fold in cleanly), but it is checked
against this registry so a removed command can't linger there silently.

A startup assertion (:func:`assert_commands_consistent`, called from
``setup_commands``) fails loudly if the registered ``@router.message(Command(...))``
handlers drift from this registry, or if a label is missing a locale — so the
four surfaces can no longer silently diverge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Cmd:
    """One Telegram command, defined ONCE for every surface that names it.

    Attributes:
        slug: the primary command word (without the leading ``/``).
        aliases: alternate command words handled by the SAME handler (e.g.
            ``/reset`` for ``/clear``). Aliases are accepted by the router but
            are NOT advertised separately in the menu.
        scope: who the command is FOR — ``"all"`` (every allowed user),
            ``"code"`` (code-level users + owner only), or ``"owner"`` (owner
            admin commands). Drives _CODE_/_OWNER_ derivation + per-user menus.
        in_menu: whether the command appears in the setMyCommands menu. Commands
            whose handlers are commented out (or are pure config reachable via
            /settings) set this False so they leave the menu in ONE place.
        label: the menu description, ``{"en": ..., "ru": ...}`` — the single
            source for the localized one-liner shown in Telegram's ``/`` menu.
        help_group: optional grouping hint for /help (informational; the help
            prose currently lives in i18n.py).
    """

    slug: str
    label: dict[str, str]
    scope: str = "all"
    in_menu: bool = True
    aliases: tuple[str, ...] = ()
    help_group: str = ""


# One row per REAL command. Menu order (in_menu rows, top-to-bottom) is the order
# here. #155: rows are FREQUENCY-RANKED to match menu.md §2 (Tier A → F), because
# Telegram only surfaces the top ~5 on mobile — the everyday trio (/new, /sessions,
# /settings) sits at the very top, rarer commands scroll below. Notes:
#   - /stop and /stream handlers are commented out → omitted entirely so they
#     can't reappear in the menu or /help (was in cmd.stop / cmd.stream + help).
#   - The common Tier-C settings (/model, /effort, /memory, /language) are now
#     in_menu=True so the "/" menu reflects menu.md §3.1 (a chat user sees Tiers
#     A–C+E); they ALSO live in the /settings hub (the inline path is canonical).
#   - scope "code"/"owner" reproduces the old _CODE_/_OWNER_ arrays; the owner
#     block order follows menu.md §2 Tier F.
COMMANDS: tuple[Cmd, ...] = (
    # — Tier A · everyday (top of the "/" menu) —
    Cmd("new", {"en": "➕ New session (starts as chat)",
                "ru": "➕ Новая сессия (создаётся как чат)"}, help_group="sessions"),
    Cmd("sessions", {"en": "Browse / switch / delete sessions",
                     "ru": "Обзор / переключение / удаление сессий"}, help_group="sessions"),
    Cmd("settings", {"en": "Open the settings menu",
                     "ru": "Открыть меню настроек"}, help_group="settings"),
    # — Tier B · common (run control + type switch; #133: /code upgrades, /chat downgrades) —
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
    # — Tier C · occasional · settings (pickers/toggles; also in the /settings hub) —
    Cmd("model", {"en": "Switch model: opus | sonnet | haiku",
                  "ru": "Сменить модель: opus | sonnet | haiku"}, help_group="settings"),
    Cmd("effort", {"en": "Reasoning depth: low … max",
                   "ru": "Глубина рассуждений: low … max"}, help_group="settings"),
    Cmd("memory", {"en": "1M context window (chat): on | off",
                   "ru": "Окно контекста 1M (чат): on | off"}, help_group="settings"),
    Cmd("language", {"en": "Choose the interface language",
                     "ru": "Выбрать язык интерфейса"}, help_group="settings"),
    # — Tier C · occasional · run + session content —
    Cmd("context", {"en": "Context-window usage",
                    "ru": "Использование окна контекста"}, help_group="run"),
    Cmd("limits", {"en": "📊 Your usage limits",
                   "ru": "📊 Ваши лимиты использования"}, help_group="run"),
    Cmd("queue", {"en": "Show the pending-prompt queue",
                  "ru": "Показать очередь запросов"}, help_group="run"),
    Cmd("clearqueue", {"en": "Clear the pending queue",
                       "ru": "Очистить очередь"}, help_group="run"),
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
    # — Tier D · code-only —
    Cmd("files", {"en": "Browse the working-dir tree (code)",
                  "ru": "Дерево рабочей папки (код)"}, scope="code", help_group="code"),
    Cmd("export", {"en": "Export working-dir files as .zip (code)",
                   "ru": "Экспорт файлов рабочей папки (.zip, код)"}, scope="code", help_group="code"),
    Cmd("maxturns", {"en": "Cap agentic turns (code)",
                     "ru": "Лимит агентных ходов (код)"}, scope="code", help_group="code"),
    # #217: surfaced into the "/" menu (code users) — these are routine code-session
    # config that was previously only typeable / buried in the hub.
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
    # — Tier E · meta —
    Cmd("help", {"en": "Show help", "ru": "Показать справку"}, help_group="meta"),
    Cmd("whoami", {"en": "Show your id and username",
                   "ru": "Показать ваш id и username"}, help_group="meta"),

    # — Tier E · secondary: registered handlers kept OUT of the menu (typeable, or
    #   reached via the inline menus). scope="code" keeps the per-user-menu
    #   derivation honest even though in_menu is False. —
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

    # — Tier F · owner-only admin (scope="owner"); appended after the shared list
    #   in the owner's private-chat command scope only (menu.md §1.8). in_menu=False
    #   keeps them out of the shared menu; they are added explicitly for the owner.
    #   Order follows menu.md §2 Tier F (users first, sandbox last). —
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
    # #231: /sandbox retired — the sandbox is now MANDATORY for all sessions, no opt-out.
    # was:
    # Cmd("sandbox", {"en": "Toggle this session's sandbox (owner)",
    #                 "ru": "Песочница сессии вкл/выкл (владелец)"},
    #     scope="owner", in_menu=False, help_group="owner"),
    # #172: owner-only streaming self-test. in_menu=False AND help_group="" → it is
    # NOT advertised in the "/" menu or /help; it is typeable only. Kept LAST.
    Cmd("test", {"en": "Simulate a streamed reply (owner self-test)",
                 "ru": "Симуляция потоковой генерации (тест владельца)"},
        scope="owner", in_menu=False, help_group=""),
)

# Locales every Cmd.label MUST cover (kept in sync with i18n.LANGUAGES via the
# assertion below; hard-coded here to avoid an import cycle with i18n at module
# load — the assertion re-checks against i18n.LANGUAGES at startup).
REQUIRED_LOCALES: tuple[str, ...] = ("en", "ru")


def by_slug() -> dict[str, Cmd]:
    """Map slug -> Cmd for quick lookup."""
    return {c.slug: c for c in COMMANDS}


def menu_slugs() -> list[str]:
    """In-menu command slugs, in registry order (replaces old _COMMAND_NAMES)."""
    return [c.slug for c in COMMANDS if c.in_menu]


def code_slugs() -> list[str]:
    """Code-only command slugs (replaces old _CODE_COMMAND_NAMES)."""
    return [c.slug for c in COMMANDS if c.scope == "code"]


def owner_slugs() -> list[str]:
    """Owner-only command slugs (replaces old _OWNER_COMMAND_NAMES)."""
    return [c.slug for c in COMMANDS if c.scope == "owner"]


def all_command_words() -> set[str]:
    """Every word that should have a handler: slugs + aliases."""
    words: set[str] = set()
    for c in COMMANDS:
        words.add(c.slug)
        words.update(c.aliases)
    return words


# Slugs intentionally registered as @router handlers but deliberately NOT carrying
# a Cmd row, OR Cmd rows with no live handler. Keep empty; documents the contract.
# (/stop, /stream handlers are commented out → no handler AND no Cmd row, so they
#  do not appear here.)
_HANDLER_EXCEPTIONS: frozenset[str] = frozenset()


def registered_handler_slugs(handlers_path: str | Path | None = None) -> set[str]:
    """Scan handlers.py for the command words bound to a live @router handler.

    Robust over editing: we parse the ACTUAL router source and only count
    UNCOMMENTED ``@router.message(Command("a", "b", ...))`` (and CommandStart is
    ignored — /start has no menu entry). Commented-out handlers (lines starting
    with ``#``) are skipped, so /stop and /stream do not count. Returns the set of
    every command word (slug + alias) that has a live handler.
    """
    path = Path(handlers_path) if handlers_path else Path(__file__).with_name("handlers.py")
    src = path.read_text(encoding="utf-8")
    words: set[str] = set()
    pat = re.compile(r'Command\(\s*((?:"[^"]+"\s*,?\s*)+)\)')
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue  # commented-out handler (e.g. /stop, /stream)
        for m in pat.finditer(line):
            for w in re.findall(r'"([^"]+)"', m.group(1)):
                words.add(w)
    return words


def assert_commands_consistent(handlers_path: str | Path | None = None,
                               languages: tuple[str, ...] | None = None) -> None:
    """Fail loudly (ValueError) if the four command surfaces have drifted.

    Checks, in order:
      1. every Cmd.label covers every required locale (en + ru, and every key in
         i18n.LANGUAGES when passed in);
      2. scope is one of the allowed values;
      3. every live @router Command handler word has a Cmd row, and every Cmd
         word (slug + alias) has a live handler — so neither side can add or
         remove a command without the other noticing.

    Called from setup_commands at startup; raises so a drift can't ship silently.
    """
    locales = tuple(languages) if languages else REQUIRED_LOCALES
    problems: list[str] = []

    # 1 + 2: labels + scope.
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

    # 3: handler <-> registry parity.
    handler_words = registered_handler_slugs(handlers_path)
    registry_words = all_command_words()
    # /start, /cancel-like control words that are handlers but not user commands:
    # CommandStart is not matched by the regex, so only Command(...) words appear.
    missing_rows = handler_words - registry_words - _HANDLER_EXCEPTIONS
    missing_handlers = registry_words - handler_words - _HANDLER_EXCEPTIONS
    for w in sorted(missing_rows):
        problems.append(f"/{w}: has a @router handler but no Cmd row")
    for w in sorted(missing_handlers):
        problems.append(f"/{w}: has a Cmd row but no live @router handler")

    if problems:
        raise ValueError(
            "command registry drift (#139) — fix commands.py / handlers.py:\n  "
            + "\n  ".join(problems)
        )
