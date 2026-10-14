"""Entrypoint for the private Telegram bot.

- Wires config, store, middleware, gate, sessions, router
- Runs long polling until interrupted
"""

import asyncio
import contextlib
import datetime
import logging
import os
import subprocess
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

from app.config import load_settings
from app.storage.db import (init_db, close_db, migrate_workdirs_to_sid,
                            migrate_workdirs_to_ulid, migrate_model_ids_to_aliases,
                            migrate_sessions_to_ulid, load_sid_cache, sandbox_uid_collisions)
from app.core import models  # Model catalog the CLI reports
from app.core import cli_update  # Stage and update the CLI
from app.telegram.rich_message import stopped_generation_of
from app.access.allowlist import Allowlist
from app.access.access import AllowlistMiddleware, LanguageMiddleware
from app.access.permissions import PermissionGate
from app.core.sessions import SessionManager
from app.telegram.handlers import build_router, setup_commands
from app import watchdog
from app import i18n
from app import DEPLOY_DIR  # Repo-root `deploy/` scripts

logger = logging.getLogger("bot")


def _configure_logging() -> None:
    """Send structured logs to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # aiogram is chatty at DEBUG; keep INFO.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    """Build every component and start polling.

    - Cleans up on shutdown
    """
    _configure_logging()

    settings = load_settings()
    logger.info(
        "Settings loaded: owner_id=%s default_model=%s base_workdir=%s db_path=%s",
        settings.owner_id,
        settings.default_model,
        settings.base_workdir,
        settings.db_path,
    )

    # Persistent per-thread state; `init_db` expects a string path.
    await init_db(str(settings.db_path))
    logger.info("Database initialised at %s", settings.db_path)

    # Restore the CLI's last-reported model catalog.
    # - Picker reads it before the first client connects
    # - Once per database: concrete model ids become family aliases
    # - Never blocks startup
    with contextlib.suppress(Exception):
        await models.load()
    with contextlib.suppress(Exception):
        n = await migrate_model_ids_to_aliases(models.family_alias)
        if n:
            logger.info("Moved %d stored model id(s) onto CLI family aliases", n)

    # Idempotent rename of workdirs from thread id to sid.
    # - Runs every startup; failure must not block start
    with contextlib.suppress(Exception):
        n = await migrate_workdirs_to_sid(str(settings.base_workdir))
        if n:
            logger.info("Migrated %d session workdir(s) to sid-based names", n)

    # Backfill a stored public ULID for each session.
    # - DB-only: workdir, transcript and jail uid stay on `session_sid`
    # - Idempotent; then load the thread-to-ULID cache
    with contextlib.suppress(Exception):
        n = await migrate_sessions_to_ulid(str(settings.base_workdir))
        if n:
            logger.info("Backfilled %d session(s) with a public ULID id", n)
    with contextlib.suppress(Exception):
        await load_sid_cache()

    # Rename workdirs from legacy sid to the public ULID.
    # - Re-encodes transcripts and re-keys uids so `resume` survives
    # - Idempotent; runs after the ULID backfill and cache
    # - Failure must not block startup
    with contextlib.suppress(Exception):
        n = await migrate_workdirs_to_ulid(str(settings.base_workdir))
        if n:
            logger.info("Migrated %d session workdir(s) to ULID names", n)

    # Doctor: scan workdirs for a host uid shared by sessions.
    # - Always empty with the uid registry, barring unhealed old collisions
    # - Filesystem-only; owner is alerted after the bot connects
    uid_collisions: dict[int, list[str]] = {}
    with contextlib.suppress(Exception):
        uid_collisions = sandbox_uid_collisions(str(settings.base_workdir))
        if uid_collisions:
            logger.warning(
                "%d sandbox uid collision(s) on disk: %s — affected sessions "
                "self-heal (re-chown to a registry uid) on their next turn.",
                len(uid_collisions),
                "; ".join(f"uid {u}: {','.join(s)}" for u, s in uid_collisions.items()),
            )
        else:
            logger.info("sandbox uid check clean (no host uid shared across sessions)")

    # One `Bot` serves two platforms.
    # - Its session routes by chat id: Telegram, or MAX namespace
    # - Downstream code never learns which platform it talks to
    # - HTML parse mode is the default
    tg_session = AiohttpSession()
    max_api = max_bridge = None
    if settings.max_bot_token:
        from app.max.bridge import MaxSession, RoutingSession
        from app.max.client import MaxApi
        max_api = MaxApi(settings.max_bot_token, base=settings.max_api_base,
                         ca_bundle=settings.max_ca_bundle or None)
        max_bridge = MaxSession(max_api)
        session = RoutingSession(tg_session, max_bridge)
    else:
        session = tg_session
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    # JSON-backed allowlist; the owner is always allowed.
    allowlist = Allowlist(settings.allowlist_path, settings.owner_id)

    # Core components share the single `Bot` instance.
    # - Session manager gets the allowlist for per-user global memory
    # - Non-owner code-session approvals are posted to the owner's chat
    gate = PermissionGate(bot, owner_id=settings.owner_id)
    sessions = SessionManager(bot, settings, gate, allowlist)

    # Best-effort restore of usage mode, rate snapshot, pinned message id.
    # - A fresh database must not block startup
    with contextlib.suppress(Exception):
        await sessions.load_persisted()

    # Poll the account usage endpoint for real subscription percent.
    # - SDK rate events only report near a limit
    # - Best-effort; the poller swallows its own errors
    with contextlib.suppress(Exception):
        sessions.start_usage_poller()

    # Start the idle-client reaper.
    # - Idle sessions release their ~400 MB subprocess
    # - History persists on disk; next message resumes
    with contextlib.suppress(Exception):
        sessions.start_reaper()

    # Start the archive-retention purger.
    # - Deletes archived bundles older than retention
    # - Runs at startup and daily; best-effort
    with contextlib.suppress(Exception):
        sessions.start_archive_purger()

    # Start the recurring-schedule runner.
    # - Fires due schedule prompts into their sessions
    # - Best-effort; the loop swallows its own errors
    with contextlib.suppress(Exception):
        sessions.start_scheduler()

    # Start the proactive OAuth token refresher.
    # - Renews the token before its ~8h expiry
    # - Avoids a 401 after a long idle gap
    # - Fail-soft; disable with `OAUTH_REFRESH=0`
    with contextlib.suppress(Exception):
        sessions.start_token_refresher()

    # Keep the Claude Code CLI current.
    # - Runs `claude update` and re-stages the jail copy
    # - Daily at `CLI_UPDATE_AT_UTC` (default 12:00); off disables
    # - New models arrive without a bot change or restart
    # - Clients move to the new binary between replies
    with contextlib.suppress(Exception):
        sessions.start_cli_updater()

    # Name-or-dispose sweep over every DM user's sessions.
    # - Unnamed placeholder sessions get named, or archived if empty
    # - Runs shortly after startup, then daily
    with contextlib.suppress(Exception):
        sessions.start_untitled_sweeper()

    # Signal READY and start watchdog before any network I/O.
    # - Also precedes sandbox setup so slow steps cannot delay READY
    # - Watchdog pings `WATCHDOG=1` only after a successful `get_me`
    # - Watchdog task is created first inside the try
    # - No-op when not under systemd
    wd_task: asyncio.Task | None = None
    max_task: asyncio.Task | None = None
    watchdog.ready()

    # Run the credential broker as a host sidecar.
    # - Keeps the subscription token out of session jails
    # - Jail gets a dummy token and broker base URL
    # - Off by default; refuses to start with an API key
    broker_proc: subprocess.Popen | None = None
    if getattr(settings, "cred_broker", False):
        with contextlib.suppress(Exception):
            broker_env = {k: v for k, v in os.environ.items()
                          if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
            broker_proc = subprocess.Popen(
                [sys.executable,
                 str(DEPLOY_DIR / "cred-broker.py"),
                 "--port", str(settings.cred_broker_port)],
                env=broker_env,
            )
            logger.info("Credential broker started on 127.0.0.1:%s",
                        settings.cred_broker_port)

    _deploy = DEPLOY_DIR

    # Compile the seccomp denylist BPF once at startup.
    # - x86_64 only; the script no-ops elsewhere
    # - Engine points bwrap's `--seccomp` fd at this file
    if getattr(settings, "sandbox_seccomp", False) and settings.sandbox_seccomp_path:
        with contextlib.suppress(Exception):
            # Compile runs off the event loop, after READY.
            # - A slow compile cannot block the loop or start-timeout
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(_deploy / "make-seccomp.py"),
                 settings.sandbox_seccomp_path], check=False, timeout=30)
            if os.path.exists(settings.sandbox_seccomp_path):
                logger.info("Seccomp filter compiled at %s",
                            settings.sandbox_seccomp_path)

    # Stage the self-contained `claude` binary world-readably.
    # - Per-session uid cannot reach root's `~/.local/bin/claude`
    # - Jail binds `/usr`, so it execs `/usr/local/bin/claude`
    # - `cli_update` also restages after each CLI update
    if getattr(settings, "sandbox_per_session_uid", False):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(cli_update.stage)

    # Egress filtering: cgroup-scoped firewall plus CONNECT proxy sidecar.
    # - Set up once; fully reverted on shutdown
    # - Rule is cgroup-scoped, so SSH and the bot are unaffected
    egress_proc: subprocess.Popen | None = None
    if getattr(settings, "sandbox_egress", False):
        with contextlib.suppress(Exception):
            # Setup runs off the event loop, post-READY.
            # - Result is captured so failure is logged loudly
            # - Example: `nf_conntrack` not loaded, rule insert fails
            # - Script self-verifies with `iptables -C`
            _eg = await asyncio.to_thread(
                subprocess.run,
                ["bash", str(_deploy / "egress-setup.sh"),
                 str(settings.cred_broker_port), str(settings.egress_proxy_port)],
                check=False, timeout=30, capture_output=True, text=True)
            if _eg.returncode == 0:
                logger.info("Egress allowlist firewall set up (cgroup-scoped)")
            else:
                logger.error("Egress allowlist setup FAILED (rc=%s) — egress is NOT "
                             "enforced; sessions fail closed at the jail cgroup-join guard. %s",
                             _eg.returncode, (_eg.stderr or "").strip()[-300:])
        with contextlib.suppress(Exception):
            proxy_env = {k: v for k, v in os.environ.items()
                         if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
            proxy_env["EGRESS_PROXY_PORT"] = str(settings.egress_proxy_port)
            if getattr(settings, "egress_allow_hosts", ""):
                proxy_env["EGRESS_ALLOW_HOSTS"] = settings.egress_allow_hosts
            egress_proc = subprocess.Popen(
                [sys.executable, str(_deploy / "egress-proxy.py"),
                 "--port", str(settings.egress_proxy_port)],
                env=proxy_env,
            )
            logger.info("Egress proxy started on 127.0.0.1:%s",
                        settings.egress_proxy_port)

    router = build_router(settings, sessions, gate, bot, allowlist)
    dp.include_router(router)

    # Allowlist enforced as an outer middleware.
    # - Unauthorized updates never reach filters or handlers
    allowlist_mw = AllowlistMiddleware(allowlist, owner_id=settings.owner_id)
    dp.message.outer_middleware(allowlist_mw)
    dp.callback_query.outer_middleware(allowlist_mw)

    # After access: resolve each user's interface locale.
    # - Auto-detected from client language; `/language` overrides
    language_mw = LanguageMiddleware()
    dp.message.outer_middleware(language_mw)
    dp.callback_query.outer_middleware(language_mw)

    # Experimental draft push button, handled outside aiogram.
    # - aiogram drops this Bot API 10.3 update type
    # - Read from the raw update, passed to session manager
    # - Only acts on a live reply draft in that chat
    async def _push_mw(handler, event, data):
        info = stopped_generation_of(event)
        if info is None:
            return await handler(event, data)
        with contextlib.suppress(Exception):
            sessions.on_generation_stopped(*info)
        return None

    dp.update.outer_middleware(_push_mw)

    try:
        # Watchdog task is created first inside the try.
        # - So the `finally` reliably cancels it
        # - READY=1 was already sent, before sandbox setup
        # - Watchdog pings only after a successful `get_me`
        # - It force-restarts only after a prolonged outage
        wd_task = asyncio.create_task(watchdog.run(bot))

        # Identify the bot; detect a bad token early.
        # - A network blip is not fatal; polling retries
        # - Real auth or other errors still propagate
        try:
            me = await bot.get_me(request_timeout=15)
            logger.info("Authorized as @%s (id=%s)", me.username, me.id)
        except (TelegramNetworkError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Startup get_me network issue (%s); continuing — polling will retry.",
                exc,
            )

        # Populate the Telegram command menu, best-effort and time-bounded.
        # - A slow Telegram must not hang startup
        # - Owner also gets owner-only commands in private chat
        # - Failure is logged, not suppressed
        try:
            await asyncio.wait_for(
                setup_commands(bot, owner_id=settings.owner_id), timeout=30
            )
        except Exception as exc:
            logger.warning("setup_commands failed; command menus not refreshed: %s", exc)

        # Alert the owner of on-disk uid collisions once connected.
        # - Best-effort, post-READY, off the startup-critical path
        if uid_collisions and settings.owner_id:
            detail = "; ".join(
                f"uid {u}: {', '.join(s)}" for u, s in uid_collisions.items()
            )
            # Stamp the alert with a UTC time.
            # - Distinguishes a restart re-run from a new collision
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            with contextlib.suppress(Exception):
                await bot.send_message(
                    settings.owner_id,
                    i18n.t("admin.uid_collision_alert", i18n.DEFAULT_LANG,
                           count=len(uid_collisions), detail=detail, ts=ts),
                )

        # The MAX long-poller feeds the same dispatcher.
        # - Its failures only log and back off
        # - A MAX outage must never take Telegram down
        if max_bridge is not None:
            from app.max.poller import MaxPoller
            try:
                max_me = await max_api.get_me()
                max_bridge.bot_user = max_me
                logger.info("MAX: authorized as @%s (id=%s)", max_me.get("username"),
                            max_me.get("user_id"))
            except Exception as exc:
                # Not fatal; the poller retries.
                # - A wrong token or untrusted CA shows here
                logger.warning("MAX: startup get_me failed (%s); polling will retry", exc)
            max_task = asyncio.create_task(MaxPoller(max_api, max_bridge, dp, bot).run())

        # Request only the update types we handle.
        # - Includes `stopped_message_generation` for the draft button
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "stopped_message_generation"],
        )
    finally:
        logger.info("Shutting down...")
        # Stop the watchdog first so it cannot ping systemd.
        if wd_task is not None:
            wd_task.cancel()
            with contextlib.suppress(BaseException):
                await wd_task
        if max_task is not None:   # Stop MAX updates before draining
            max_task.cancel()
            with contextlib.suppress(BaseException):
                await max_task
        # Graceful drain first: stop new turns, await in-flight ones.
        # - Avoids killing a turn mid-generation or tearing its transcript
        # - Bounded below `TimeoutStopSec=60`
        # - Needs `KillMode=mixed` so SIGTERM skips jailed children
        with contextlib.suppress(Exception):
            await sessions.drain(timeout=40.0)
        # Disconnect live sessions before closing the DB.
        # - Cancels workers and closes `claude` subprocesses
        # - In-flight writes must not hit a closed connection
        # - Best-effort: teardown errors must not mask the shutdown reason
        with contextlib.suppress(Exception):
            await sessions.aclose()
        # Stop the credential broker sidecar if running.
        if broker_proc is not None and broker_proc.poll() is None:
            with contextlib.suppress(Exception):
                broker_proc.terminate()
                broker_proc.wait(timeout=5)
        # Stop the egress proxy sidecar and revert the firewall.
        # - Removes the cgroup jump and the `SBX_EGRESS` chain
        # - A stopped bot never leaves a dangling rule
        if egress_proc is not None and egress_proc.poll() is None:
            with contextlib.suppress(Exception):
                egress_proc.terminate()
                egress_proc.wait(timeout=5)
        if getattr(settings, "sandbox_egress", False):
            with contextlib.suppress(Exception):
                subprocess.run(["bash", str(_deploy / "egress-teardown.sh")],
                               check=False, timeout=15)
        await close_db()
        await bot.session.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("bot").info("Interrupted, exiting.")
