"""Liveness / connection watchdog — keeps the bot self-healing under a supervisor.

The bot polls Telegram; if the network path to Telegram drops for a while the
process can either die (then a supervisor must restart it) or, worse, stay alive
but wedged (no supervisor restart fires on a live process). This module closes
both gaps by reporting health to **systemd's watchdog**:

* :func:`ready` sends ``READY=1`` once polling starts (for ``Type=notify``).
* :func:`run` probes Telegram (``get_me``) on a fixed cadence and sends
  ``WATCHDOG=1`` **only on success**. If the bot can no longer reach Telegram
  (connection dropped, polling wedged, event loop blocked), the pings stop and
  systemd's ``WatchdogSec`` force-restarts the unit — which, with
  ``Restart=always`` + ``StartLimitIntervalSec=0``, retries until Telegram is
  reachable again, with zero manual intervention. Short blips are tolerated
  within ``WatchdogSec`` (the probe keeps succeeding between them).

Everything here is a best-effort no-op when NOT run under systemd (no
``NOTIFY_SOCKET``), so running the bot manually (or in tests) is unaffected — it
just probes Telegram and writes an optional heartbeat file. All OS/supervisor
coupling stays in this one small module + ``deploy/tg-bot.service``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

log = logging.getLogger("watchdog")


def _sd_notify(state: str) -> None:
    """Send one sd_notify datagram; no-op when not under systemd.

    Honors the abstract-namespace form (``NOTIFY_SOCKET`` starting with ``@``).
    Never raises — a watchdog that crashes the bot would defeat its purpose.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            # '@'-prefixed address is an abstract socket → leading NUL byte.
            target = "\0" + addr[1:] if addr.startswith("@") else addr
            sock.sendto(state.encode("utf-8"), target)
    except OSError:
        pass


def ready() -> None:
    """Tell systemd the service finished starting (used with ``Type=notify``)."""
    _sd_notify("READY=1")


def _interval_seconds() -> float:
    """Probe cadence. Under a systemd watchdog, ping at half of ``WatchdogSec``
    (the manual's recommendation) so a couple of misses still fit the window;
    otherwise default to 30s."""
    usec = os.environ.get("WATCHDOG_USEC", "")
    if usec.isdigit() and int(usec) > 0:
        return max(5.0, (int(usec) / 1_000_000) / 2)
    return 30.0


async def run(bot, heartbeat_file: str | None = None) -> None:
    """Probe Telegram forever; ping systemd's watchdog on each success.

    Cancel the returned task on shutdown. ``bot`` is the aiogram ``Bot`` (so the
    probe traverses the SAME session/proxy as real traffic). ``heartbeat_file``
    (or env ``HEARTBEAT_FILE``) is touched with a unix timestamp on each success,
    for non-systemd supervisors / debugging.
    """
    interval = _interval_seconds()
    hb = heartbeat_file or os.environ.get("HEARTBEAT_FILE") or None
    timeout = max(5.0, interval * 0.8)
    under_systemd = bool(os.environ.get("NOTIFY_SOCKET"))
    log.info(
        "watchdog: probing Telegram every %.0fs (systemd=%s, heartbeat=%s)",
        interval, under_systemd, hb or "-",
    )
    consecutive = 0
    while True:
        try:
            await asyncio.wait_for(bot.get_me(), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # network/timeout/API — treat as "unreachable"
            consecutive += 1
            # Deliberately do NOT ping on failure: under systemd, WatchdogSec then
            # restarts us; the restart loop self-heals once Telegram is back.
            log.warning("watchdog: Telegram unreachable (%d in a row): %s",
                        consecutive, exc)
        else:
            if consecutive:
                log.info("watchdog: Telegram reachable again after %d failure(s)",
                         consecutive)
            consecutive = 0
            _sd_notify("WATCHDOG=1")
            if hb:
                try:
                    with open(hb, "w", encoding="utf-8") as fh:
                        fh.write(str(int(time.time())))
                except OSError:
                    pass
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
