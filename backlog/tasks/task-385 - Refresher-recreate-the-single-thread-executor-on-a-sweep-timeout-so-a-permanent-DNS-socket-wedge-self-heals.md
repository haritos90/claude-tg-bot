---
id: TASK-385
title: >-
  Refresher: recreate the single-thread executor on a sweep timeout so a
  permanent DNS/socket wedge self-heals
status: Done
assignee: []
created_date: '2026-07-21 16:01'
updated_date: '2026-07-21 17:14'
labels:
  - reliability
  - auth
dependencies: []
priority: high
ordinal: 23362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The #380 comment claims a timed-out sweep self-heals once the resolver returns, but the size-1 ThreadPoolExecutor is created once and never recreated. A PERMANENTLY wedged getaddrinfo thread occupies the only worker forever: every later sweep queues behind it and times out, the token is never refreshed until process restart, yet the liveness heartbeat keeps logging "alive" (looks-healthy / is-broken). Two secondary effects: the queue grows by one refresh_now_sync per sweep for the whole wedge (unbounded), and when the wedge clears the worker fires N back-to-back UNCONDITIONAL refreshes (refresh_now_sync has no skew gate), rotating the refresh_token N times and risking an OAuth rate-limit / replay lockout that would revoke the very login the feature protects. Several loop-robustness nits in the same function are folded in. Found in a deeper review of the token-refresh batch.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 On a sweep TimeoutError the executor is replaced (shutdown(wait=False, cancel_futures=True) + a fresh max_workers=1 pool) so the next sweep always gets a free worker: a permanent wedge recovers without a process restart, the queued backlog is dropped, and no drain-burst of back-to-back refresh_token rotations occurs
- [x] #2 The #380 self-heal comment is corrected to say it self-heals only for a TRANSIENT wedge (a permanent one is bounded by the executor recreate), not unconditionally
- [x] #3 A genuinely non-functional sweep (creds unreadable / no refresh token) is not silently counted as a healthy reset of the consecutive-failure counter
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented AC1-AC3 + the heartbeat nit (F). token_refresh.refresh_loop: on asyncio.TimeoutError the executor is REPLACED (shutdown(wait=False, cancel_futures=True) + a fresh max_workers=1 pool), so a permanent DNS/socket wedge self-heals (the next sweep gets a live worker) and the queued backlog is dropped (no drain-burst of back-to-back token rotations). The comment now states self-heal is for a TRANSIENT wedge, a permanent one bounded by the recreate. Skip reclassification: only 'skip: Ns left' is a healthy skip (resets the streak); 'skip: creds unreadable' / 'skip: no refresh token' are treated as failures (escalate, do not reset). The generic except sets status=fail:ExcName so the heartbeat does not report a stale status, and the heartbeat log is wrapped in contextlib.suppress so a raising handler cannot escape to finally and kill the loop. New tests: test_refresh_loop_timeout_escalates_on_repeat and test_refresh_loop_broken_skip_counts_as_failure. Deferred (not ACs): E — the loop-side creds read at the top of maybe_refresh is still unbounded by wait_for (low likelihood: a local small-file read wedging); G — the atexit join-hang on a wedged non-daemon worker is inherent to the abandon-thread design (force-reaped by systemd). Full suite 294 passed; ruff clean; restarted + Run polling + refresher startup shows deadline 120s.
<!-- SECTION:NOTES:END -->
