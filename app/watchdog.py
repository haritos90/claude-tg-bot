"""Liveness watchdog that keeps the bot self-healing under systemd.

- `ready` sends `READY=1` once polling starts
- `run` probes `get_me`, pings `WATCHDOG=1` only on success
- stopped pings let `WatchdogSec` force a restart
- no-op without `NOTIFY_SOCKET`, so manual runs are unaffected
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

log = logging.getLogger("watchdog")


def _sd_notify(state: str) -> None:
    """Send one sd_notify datagram; no-op outside systemd.

    - handles abstract sockets (`NOTIFY_SOCKET` starting with `@`)
    - never raises; a crashing watchdog defeats its purpose
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            # An `@` prefix means an abstract socket: leading NUL byte.
            target = "\0" + addr[1:] if addr.startswith("@") else addr
            sock.sendto(state.encode("utf-8"), target)
    except OSError:
        pass


def ready() -> None:
    """Tell systemd the service finished starting.

    - used with `Type=notify`
    """
    _sd_notify("READY=1")


def _interval_seconds() -> float:
    """Probe interval: half of `WatchdogSec`, else 30s.

    - half leaves room for a couple of missed pings
    """
    usec = os.environ.get("WATCHDOG_USEC", "")
    if usec.isdigit() and int(usec) > 0:
        return max(5.0, (int(usec) / 1_000_000) / 2)
    return 30.0


async def run(bot, heartbeat_file: str | None = None) -> None:
    """Probe Telegram forever; ping systemd on each success.

    - cancel the returned task on shutdown
    - `bot` is the aiogram `Bot`; probes share its session
    - `heartbeat_file` or `HEARTBEAT_FILE` is touched with a timestamp
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
        except Exception as exc:  # network, timeout or API: unreachable
            consecutive += 1
            # Deliberately no ping on failure; systemd restarts us.
            # - the restart loop self-heals once Telegram returns
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
