---
id: TASK-386
title: >-
  Test coverage for the #380 token-refresh fixes: sessions login-expiry banner
  untested; timeout-branch WARNING escalation untested
status: Done
assignee: []
created_date: '2026-07-21 16:02'
updated_date: '2026-07-21 17:14'
labels:
  - reliability
  - test
dependencies: []
priority: medium
ordinal: 24362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two coverage gaps for the #380 hardening. The sessions-side login-expiry banner (the headline #380 fix) has zero tests, and the timeout-branch WARNING escalation this commit changed is not asserted because the wedged-sweep test was loosened from WARNING to INFO. A regression on either would pass green.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 SessionManager._login_expiry_banner is covered: owner-gate (non-owner and owner_id None to None), the ~once/day throttle, and the core invariant that _login_warn_last is spent ONLY when a banner is actually shown (a None/far-future login-seconds result must not advance it)
- [x] #2 The timeout-branch escalation is covered: >=2 consecutive sweep timeouts log a WARNING record containing 'sweep exceeded' and '2 consecutive'; a lone timeout stays INFO
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. Added test_login_expiry_banner_owner_gate_read_throttle_and_display_spend (owner-gate; the once/day creds-read throttle — no second read on immediate re-call and a read outside the window still throttled; and that _login_expiry_banner does not spend the display throttle). Added test_refresh_loop_timeout_escalates_on_repeat pinning the TIMEOUT branch level: 1st timeout INFO with '1 consecutive', 2nd WARNING with '2 consecutive' — the guard the wedged-sweep test lacked (it captured at INFO and only matched the substring). The pre-existing wedged-sweep test is left as the loop-keeps-ticking check. Full suite 294 passed; ruff clean.
<!-- SECTION:NOTES:END -->
