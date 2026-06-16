"""Entrypoint for the private Telegram bot.

Wires together configuration, the SQLite store, the access-control
middleware, the permission gate, the per-thread session manager and the
aiogram router, then runs long polling until interrupted.

Run with:  python bot.py   (from the project directory, with a .env present)
"""

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import load_settings
from db import init_db, close_db, migrate_workdirs_to_sid
from allowlist import Allowlist
from access import AllowlistMiddleware, LanguageMiddleware
from permissions import PermissionGate
from sessions import SessionManager
from handlers import build_router, setup_commands

logger = logging.getLogger("bot")


def _configure_logging() -> None:
    """Send structured logs to stdout (visible in journald / docker logs)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # aiogram is fairly chatty at DEBUG; keep it at INFO.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    """Build every component and start polling. Cleans up on shutdown."""
    _configure_logging()

    settings = load_settings()
    logger.info(
        "Settings loaded: owner_id=%s default_model=%s base_workdir=%s db_path=%s",
        settings.owner_id,
        settings.default_model,
        settings.base_workdir,
        settings.db_path,
    )

    # Persistent per-thread state. init_db expects a string path.
    await init_db(str(settings.db_path))
    logger.info("Database initialised at %s", settings.db_path)

    # #140: one-time, idempotent rename of per-session workdirs from the raw
    # numeric thread_id to the stable public sid. Runs every startup (a no-op
    # once migrated); a hiccup here must never block the bot from starting.
    with contextlib.suppress(Exception):
        n = await migrate_workdirs_to_sid(str(settings.base_workdir))
        if n:
            logger.info("Migrated %d session workdir(s) to sid-based names (#140)", n)

    # The bot uses HTML parse mode by default; the markup helpers emit HTML.
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    # JSON-backed allowlist with the owner always allowed.
    allowlist = Allowlist(settings.allowlist_path, settings.owner_id)

    # Core components, all sharing the single Bot instance. The session manager
    # gets the allowlist so it can resolve per-user GLOBAL MEMORY at build time.
    gate = PermissionGate(bot)
    sessions = SessionManager(bot, settings, gate, allowlist)

    # Best-effort restore of usage mode, the persisted rate snapshot and the
    # pinned message id. A fresh database must not block startup.
    with contextlib.suppress(Exception):
        await sessions.load_persisted()

    router = build_router(settings, sessions, gate, bot, allowlist)
    dp.include_router(router)

    # Allowlist access enforced as an OUTER middleware so unauthorized
    # updates never reach filters or handlers.
    allowlist_mw = AllowlistMiddleware(allowlist)
    dp.message.outer_middleware(allowlist_mw)
    dp.callback_query.outer_middleware(allowlist_mw)

    # After access: resolve each allowed user's interface locale (auto-detected
    # from the Telegram client language, overridable via /language).
    language_mw = LanguageMiddleware()
    dp.message.outer_middleware(language_mw)
    dp.callback_query.outer_middleware(language_mw)

    try:
        try:
            me = await bot.get_me()
        except Exception:
            logger.error(
                "Failed to authenticate with Telegram — check TELEGRAM_BOT_TOKEN"
            )
            raise
        logger.info("Authorized as @%s (id=%s)", me.username, me.id)

        # Populate the Telegram "/" command menu; failures are non-fatal. The
        # owner also gets the owner-only admin commands in their private chat.
        with contextlib.suppress(Exception):
            await setup_commands(bot, owner_id=settings.owner_id)

        # Only the update types we actually handle are requested from Telegram.
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        logger.info("Shutting down...")
        # Disconnect live Claude sessions (cancel workers + close the claude CLI
        # subprocesses) BEFORE closing the DB, so an in-flight turn's best-effort
        # writes are not aimed at a closed connection. Best-effort: a teardown
        # error must not mask the original shutdown reason.
        with contextlib.suppress(Exception):
            await sessions.aclose()
        await close_db()
        await bot.session.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("bot").info("Interrupted, exiting.")
