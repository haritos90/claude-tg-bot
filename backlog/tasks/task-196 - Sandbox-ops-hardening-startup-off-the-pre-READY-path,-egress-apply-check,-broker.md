---
id: TASK-196
title: "Sandbox ops hardening: startup off the pre-READY path, egress-apply check, broker idle timeout"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 196
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Hardening: the bot reports "ready" to the system faster on slow hosts, a failed network-isolation setup now logs a loud error instead of failing silently, and a hung upstream connection is dropped sooner.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three robustness follow-ups from the #119 audit. (1) `bot.py` ran `make-seccomp.py` + `egress-setup.sh` (`subprocess.run`, timeout 30 each) synchronously BEFORE `watchdog.ready()`, delaying READY on a slow box — moved `watchdog.ready()` + the watchdog task to fire ABOVE the (local-only) sandbox setup, and wrapped both `subprocess.run`s in `asyncio.to_thread` so the loop/watchdog stay responsive; the #158 no-network-before-READY invariant is preserved (pollers are background tasks). (2) `egress-setup.sh` used `-m conntrack` with no `modprobe` — if `nf_conntrack` wasn't autoloaded the rule insert failed under `set -e` and egress went silently unenforced; added `modprobe nf_conntrack` + a post-setup `iptables -C` verification of the cgroup→chain jump that exits non-zero on failure, and `bot.main` now captures the rc and logs LOUDLY (`error`) instead of suppressing it. (3) the broker's upstream `HTTPSConnection(timeout=600)` had no idle cap — lowered to a 180 s per-socket idle-read timeout (`_UPSTREAM_IDLE_TIMEOUT`) so a wedged upstream frees the thread in 3 min not 10, with ample headroom for live SSE. Verified live: READY/watchdog log before egress setup; egress jump + conntrack rule present (`iptables -C` passes); seccomp recompiled; broker up; polling; no errors.
<!-- SECTION:NOTES:END -->

