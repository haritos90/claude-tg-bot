"""Entrypoint for the private Telegram bot.

Wires together configuration, the SQLite store, the access-control
middleware, the permission gate, the per-thread session manager and the
aiogram router, then runs long polling until interrupted.

Run with:  python bot.py   (from the project directory, with a .env present)
"""

import asyncio
import contextlib
import datetime
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError

from config import load_settings
from db import init_db, close_db, migrate_workdirs_to_sid, sandbox_uid_collisions
from allowlist import Allowlist
from access import AllowlistMiddleware, LanguageMiddleware
from permissions import PermissionGate
from sessions import SessionManager
from handlers import build_router, setup_commands
import watchdog
import i18n

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

    # #221 doctor: scan on-disk session workdirs for any host uid shared by >1 session
    # (a per-session isolation break). With the uid registry this is always empty; it
    # surfaces a PRE-#221 collision not yet healed (heals on the sessions' next turn).
    # Filesystem-only → safe here; the owner is alerted after the bot connects (below).
    uid_collisions: dict[int, list[str]] = {}
    with contextlib.suppress(Exception):
        uid_collisions = sandbox_uid_collisions(str(settings.base_workdir))
        if uid_collisions:
            logger.warning(
                "#221: %d sandbox uid collision(s) on disk: %s — affected sessions "
                "self-heal (re-chown to a registry uid) on their next turn.",
                len(uid_collisions),
                "; ".join(f"uid {u}: {','.join(s)}" for u, s in uid_collisions.items()),
            )
        else:
            logger.info("#221: sandbox uid check clean (no host uid shared across sessions)")

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

    # #135: start polling the account usage endpoint so the footer / pinned / status
    # show the REAL subscription % even when idle (the SDK rate-events only report it
    # near a limit). Best-effort; the poller swallows its own errors.
    with contextlib.suppress(Exception):
        sessions.start_usage_poller()

    # #179: start the idle-client reaper so idle sessions release their ~400 MB
    # claude subprocess (history persists on disk; resume rebuilds on next message).
    with contextlib.suppress(Exception):
        sessions.start_reaper()

    # #178: start the archive-retention purger (deletes deleted-session bundles older
    # than the configured retention; runs at startup + daily). Best-effort.
    with contextlib.suppress(Exception):
        sessions.start_archive_purger()

    # #191: start the proactive OAuth token refresher so the on-disk subscription token
    # is renewed before its ~8h expiry — a turn after a long idle gap never 401s on a
    # stale token (the reaper kills the subprocess but never rotates the credential).
    # Best-effort + fail-soft; disable with OAUTH_REFRESH=0.
    with contextlib.suppress(Exception):
        sessions.start_token_refresher()

    # #196: Mark the service "up" to systemd IMMEDIATELY (sd_notify READY=1) and start the
    # watchdog BEFORE any network I/O AND before the (local-only) sandbox setup below —
    # so a slow box's seccomp-compile / egress-firewall steps can't delay READY and trip a
    # Type=notify start-timeout (#158). Everything before this point is local + non-blocking
    # (the pollers are background tasks). The watchdog still pings WATCHDOG=1 only after a
    # successful get_me, well within WatchdogSec. No-op when not under systemd.
    # (#158 invariant preserved: still NO synchronous network I/O before this line.)
    # #234: this init is the finally's guard. The watchdog TASK is created as the FIRST
    # statement inside the try below (it used to be created right here, OUTSIDE the try,
    # so a raise during the sandbox setup that follows could leak it). watchdog.ready()
    # stays here — before the local sandbox setup — so that setup can't delay READY.
    wd_task: asyncio.Task | None = None
    watchdog.ready()

    # #119b: when the credential broker is enabled, run it as a host sidecar so the
    # subscription token can stay OUT of every session jail (the jail gets a dummy token
    # + ANTHROPIC_BASE_URL pointing here; the broker injects the real bearer). Off by
    # default; the broker self-refuses to start if an API key is in the env (P0).
    broker_proc: subprocess.Popen | None = None
    if getattr(settings, "cred_broker", False):
        with contextlib.suppress(Exception):
            broker_env = {k: v for k, v in os.environ.items()
                          if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
            broker_proc = subprocess.Popen(
                [sys.executable,
                 str(Path(__file__).resolve().parent / "deploy" / "cred-broker.py"),
                 "--port", str(settings.cred_broker_port)],
                env=broker_env,
            )
            logger.info("Credential broker (#119b) started on 127.0.0.1:%s",
                        settings.cred_broker_port)

    _deploy = Path(__file__).resolve().parent / "deploy"

    # #119e: compile the seccomp denylist BPF once at startup (x86_64 only — make-seccomp.py
    # no-ops on other arches). The engine points bwrap's --seccomp fd at this file per jail.
    if getattr(settings, "sandbox_seccomp", False) and settings.sandbox_seccomp_path:
        with contextlib.suppress(Exception):
            # #196: off the event loop so a slow compile can't block the loop. Runs
            # post-READY (#234: now also pre-watchdog-task; READY=1 is already sent so a
            # slow compile can't trip the start-timeout regardless).
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(_deploy / "make-seccomp.py"),
                 settings.sandbox_seccomp_path], check=False, timeout=30)
            if os.path.exists(settings.sandbox_seccomp_path):
                logger.info("Seccomp filter (#119e) compiled at %s",
                            settings.sandbox_seccomp_path)

    # #119: when per-session uid is on, the jail runs as a non-root uid that can't reach
    # ~/.local/bin/claude (/root is 0700). Stage the (self-contained) binary world-readably
    # at /usr/local/bin/claude so the jail (which binds /usr) can exec it. Refresh only on
    # a version change (a marker records the resolved source path).
    if getattr(settings, "sandbox_per_session_uid", False):
        with contextlib.suppress(Exception):
            src = os.path.realpath(shutil.which("claude")
                                   or os.path.expanduser("~/.local/bin/claude"))
            dst, marker = "/usr/local/bin/claude", "/usr/local/bin/claude.src"
            cur = ""
            if os.path.exists(marker):
                with open(marker, encoding="utf-8") as fh:
                    cur = fh.read().strip()
            if src and os.path.exists(src) and (cur != src or not os.path.exists(dst)):
                tmp = dst + ".tmp"
                shutil.copy2(src, tmp)
                os.chmod(tmp, 0o755)
                os.replace(tmp, dst)
                with open(marker, "w", encoding="utf-8") as fh:
                    fh.write(src)
                logger.info("Staged sandbox claude binary at %s (from %s)", dst, src)

    # #119c: when egress filtering is on, set up the cgroup-scoped firewall once (fully
    # reverted on shutdown) and run the CONNECT allowlist proxy as a host sidecar. The
    # firewall match is scoped to the sandbox cgroup, so it can never affect SSH / the bot.
    egress_proc: subprocess.Popen | None = None
    if getattr(settings, "sandbox_egress", False):
        with contextlib.suppress(Exception):
            # #196: off the event loop (post-READY); capture the result so a FAILED setup
            # (e.g. nf_conntrack not loaded → rule insert fails) is logged loudly instead of
            # silently leaving egress unenforced. The script self-verifies with `iptables -C`
            # and exits non-zero if the rule did not land.
            _eg = await asyncio.to_thread(
                subprocess.run,
                ["bash", str(_deploy / "egress-setup.sh"),
                 str(settings.cred_broker_port), str(settings.egress_proxy_port)],
                check=False, timeout=30, capture_output=True, text=True)
            if _eg.returncode == 0:
                logger.info("Egress allowlist (#119c) firewall set up (cgroup-scoped)")
            else:
                logger.error("Egress allowlist (#119c) setup FAILED (rc=%s) — egress is NOT "
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
            logger.info("Egress proxy (#119c) started on 127.0.0.1:%s",
                        settings.egress_proxy_port)

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
        # #196/#234: watchdog.ready() (READY=1) is sent ABOVE, before the local sandbox
        # setup, so that setup can't delay READY. The watchdog TASK is created HERE — the
        # first statement inside the try — so the finally reliably cancels it. Creating it
        # is instant and non-blocking; it runs its own Telegram probe loop and pings
        # WATCHDOG=1 only after a successful get_me (never during setup), so creating it
        # just after the few seconds of sandbox setup is well within WatchdogSec. The
        # watchdog governs ongoing reachability and force-restarts only after a PROLONGED
        # outage, never a startup blip.
        wd_task = asyncio.create_task(watchdog.run(bot))

        # Identify the bot (nice log + early bad-token detection). A network blip
        # here is NOT fatal — polling retries on its own — but a real auth error
        # (or any non-network failure) still propagates and stops the bot.
        try:
            me = await bot.get_me(request_timeout=15)
            logger.info("Authorized as @%s (id=%s)", me.username, me.id)
        except (TelegramNetworkError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Startup get_me network issue (%s); continuing — polling will retry.",
                exc,
            )

        # Populate the Telegram "/" command menu; best-effort AND time-bounded so a
        # slow Telegram can't hang startup before polling begins. The owner also
        # gets the owner-only admin commands in their private chat.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                setup_commands(bot, owner_id=settings.owner_id), timeout=30
            )

        # #221: if the doctor found on-disk uid collisions, alert the owner now that the
        # bot is connected (best-effort, post-READY — off the startup-critical path).
        if uid_collisions and settings.owner_id:
            detail = "; ".join(
                f"uid {u}: {', '.join(s)}" for u, s in uid_collisions.items()
            )
            # #221: stamp the check with a UTC time so a recurring alert can be told
            # apart from an earlier one (e.g. a restart re-runs the doctor on the same
            # not-yet-self-healed workdirs vs a genuinely new collision).
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            with contextlib.suppress(Exception):
                await bot.send_message(
                    settings.owner_id,
                    i18n.t("admin.uid_collision_alert", i18n.DEFAULT_LANG,
                           count=len(uid_collisions), detail=detail, ts=ts),
                )

        # Only the update types we actually handle are requested from Telegram.
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        logger.info("Shutting down...")
        # Stop the watchdog first so it cannot ping systemd during teardown.
        if wd_task is not None:
            wd_task.cancel()
            with contextlib.suppress(BaseException):
                await wd_task
        # Disconnect live Claude sessions (cancel workers + close the claude CLI
        # subprocesses) BEFORE closing the DB, so an in-flight turn's best-effort
        # writes are not aimed at a closed connection. Best-effort: a teardown
        # error must not mask the original shutdown reason.
        with contextlib.suppress(Exception):
            await sessions.aclose()
        # #119b: stop the credential broker sidecar (if running).
        if broker_proc is not None and broker_proc.poll() is None:
            with contextlib.suppress(Exception):
                broker_proc.terminate()
                broker_proc.wait(timeout=5)
        # #119c: stop the egress proxy sidecar + REVERT the firewall (remove the cgroup
        # jump + the SBX_EGRESS chain) so a stopped bot never leaves a dangling rule.
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
