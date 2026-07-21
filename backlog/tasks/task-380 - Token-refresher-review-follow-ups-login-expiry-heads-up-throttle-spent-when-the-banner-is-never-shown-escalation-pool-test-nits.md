---
id: TASK-380
title: >-
  Token-refresher review follow-ups: login-expiry heads-up throttle spent when
  the banner is never shown; escalation/pool/test nits
status: Done
assignee: []
created_date: '2026-07-20 12:43'
updated_date: '2026-07-20 13:26'
labels:
  - reliability
  - auth
dependencies: []
priority: medium
ordinal: 18362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Defects and nits found reviewing the token-refresher hardening batch (task-378/379). The headline is a real bug: the once/day login-expiry heads-up can be silently swallowed by a turn that ends with no final text.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The login-expiry heads-up throttle (_login_warn_last) is spent only when the banner is actually displayed, not on a turn that ends with no final text
- [x] #2 Escalation and expiry-boundary behavior are covered by tests (reset-on-success; exact warn-days boundary)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Fixed in sessions.py + token_refresh.py + cred-broker.py (replaced lines kept commented with #380). sessions.py: the login-expiry banner is computed inside the display branch and only when the final text is non-empty, so the ~once/day throttle (_login_warn_last) is spent only when the banner is actually shown — the segmented-empty cancel path and an empty final flush no longer eat the day heads-up. _login_expiry_banner checks the throttle BEFORE reading the creds file (no per-turn file open on the event loop). token_refresh.py: the sweep-timeout path escalates to WARNING only on a repeat (fails>=2), matching the fail-status path (first timeout is INFO); added a note that repeated timeouts behind one wedged thread are expected and self-heal. cred-broker.py: reworded the handle_error comment to the disconnect points it actually covers (request-body + idle keep-alive reads; a mid-response-body disconnect is already handled by _proxy). tests: added reset-on-success (consecutive-only escalation) and the exact warn-days boundary; the wedged-sweep test now captures at INFO. Full suite 291 passed; ruff clean; restarted + Run polling + refresher startup line shows (deadline 120s).
<!-- SECTION:NOTES:END -->
