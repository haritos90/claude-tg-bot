---
id: decision-15
title: "24/7 supervision: systemd Type=notify watchdog; no network I/O before READY"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The bot must survive crashes, dropped Telegram connections, and boots, and must NOT flap on a flaky network link at startup.

## Decision

A systemd `Type=notify` unit with `WatchdogSec` + `Restart=always`. The watchdog sends `READY=1` BEFORE any network I/O (else a flaky Telegram link stalls readiness -> start-timeout flap) and `WATCHDOG=1` only after a successful `get_me`; a >3-min Telegram blackout forces a restart. All network I/O stays OFF the pre-READY path and the startup `get_me` is non-fatal on network errors.

## Consequences

- Reliable auto-recovery from crash / blackout / boot with no readiness flap.
- One poller per token — a stray manual `python -m app` next to the service causes a 409; stop the unit, don't `pkill`.
- Every future startup change must keep network I/O off the pre-READY path.

**Source tasks:** #158, #137, #196
