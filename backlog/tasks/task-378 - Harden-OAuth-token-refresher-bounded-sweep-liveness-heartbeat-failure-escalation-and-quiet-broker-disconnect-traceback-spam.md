---
id: TASK-378
title: >-
  Harden OAuth token refresher (bounded sweep + liveness heartbeat + failure
  escalation) and quiet broker disconnect traceback spam
status: Done
assignee: []
created_date: '2026-07-19 07:49'
labels:
  - reliability
  - auth
  - observability
dependencies: []
ordinal: 16362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The proactive OAuth refresher (#191) could stop renewing the on-disk token and go completely silent in the journal. Two defects: (1) a sweep runs a blocking refresh whose only timeout is urllib's socket timeout, which does NOT cover DNS resolution (getaddrinfo runs before the socket timeout is armed) — a wedged resolver parks the loop indefinitely with no further log output; (2) a healthy no-op sweep logs nothing (silent skip), so a STOPPED loop is indistinguishable from a healthy idle one. Separately, the credential broker dumped a full multi-line traceback per mid-stream client disconnect (a reaped/cancelled turn), burying the low-rate refresher lines in the shared journal. Observed as an outage where the refresh_token was revoked server-side, refreshes failed, and after a few hours the loop went dark with no trace until a manual re-login.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each refresh sweep is bounded by a deadline so a blocked DNS/socket call cannot park the loop; the loop logs the timeout and continues
- [ ] #2 The blocking refresh runs on a dedicated single-thread executor so an abandoned sweep never starves the shared default executor
- [ ] #3 A liveness heartbeat is logged every N sweeps so a stopped loop is a visible gap; consecutive failures escalate INFO->WARNING with a re-login hint
- [ ] #4 The broker logs one line for an expected client disconnect (ConnectionReset/BrokenPipe/ConnectionAborted) instead of a full traceback
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
app/core/token_refresh.py: refresh_loop now wraps each maybe_refresh in asyncio.wait_for(sweep_deadline; default 120s via OAUTH_REFRESH_SWEEP_DEADLINE_SEC) and runs the blocking refresh on a dedicated concurrent.futures.ThreadPoolExecutor(max_workers=1) so a timed-out (abandoned) sweep leaks at most one thread there, never the shared pool. Added a liveness heartbeat every OAUTH_REFRESH_HEARTBEAT_EVERY sweeps (default 6, ~3h at 30-min sweeps) and consecutive-failure escalation to WARNING with a 'manual re-login likely needed' hint. maybe_refresh gained an optional executor param (backward-compatible; falls back to asyncio.to_thread). Old loop body kept commented with the #378 ref. deploy/cred-broker.py: _Server.handle_error logs a one-liner for ConnectionResetError/BrokenPipeError/ConnectionAbortedError instead of socketserver's default traceback. Tests added: executor path, wedged-sweep bounding, escalation+heartbeat. Full suite 285 passed; ruff clean; restarted and verified Run polling + refresher startup line shows '(deadline 120s)' + broker probe 200. Note: the broker (_Creds.token, re-read by mtime) and the refresher both re-read the creds file, so a manual re-login is picked up without a restart; restart still recommended after re-login to guarantee a wedged loop is cleared.
<!-- SECTION:NOTES:END -->
