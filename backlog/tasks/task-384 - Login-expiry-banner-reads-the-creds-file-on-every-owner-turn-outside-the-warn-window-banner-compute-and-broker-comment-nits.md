---
id: TASK-384
title: >-
  Login-expiry banner reads the creds file on every owner turn outside the warn
  window; banner-compute and broker-comment nits
status: Done
assignee: []
created_date: '2026-07-21 15:44'
updated_date: '2026-07-21 17:14'
labels:
  - reliability
  - auth
dependencies: []
priority: medium
ordinal: 22362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-up nits from reviewing the token-refresh / login-expiry batch (task-378/379/380). The headline: the ~once/day throttle in SessionManager._login_expiry_banner does NOT gate the credentials-file read for the ~27 of 30 days outside the warn window, contradicting the #380 comment that claims the read now happens once/day rather than every owner turn-finish. Two smaller seams in the same finalize path, plus a comment-accuracy nit in the broker, are folded in.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The credentials file is read at most ~once/day on the owner turn-finish path (throttle the READ, not just the banner display), so an owner turn outside the warn window does no per-turn creds-file open+parse on the event loop
- [x] #2 The banner compute on the finalize path cannot skip the answer's finish()/log_message() if it ever raises, and does not spend the day's throttle when the banner is not actually delivered
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. sessions.py: added SessionManager._login_check_last (read throttle). _login_expiry_banner gates the creds read on _login_check_last (bumped on read), so an owner turn OUTSIDE the warn window no longer reopens the credentials file every finish; the display throttle (_login_warn_last) is checked first but no longer spent inside the function. The finalize caller guards the banner compute in contextlib.suppress (a broken creds read cannot drop the answer) and spends _login_warn_last only AFTER streamer.finish() delivers, so a failed finish does not eat the day heads-up. db.log_message still logs the clean flush_text (banner display-only). cred-broker.py: reworded the handle_error comment — the mid-response-body disconnect is owned by _proxy (whose send_error(502) is itself swallowed, so no 502 reaches the client); this override covers the request-body + idle keep-alive reads. Old code kept commented with #384. New test test_login_expiry_banner_owner_gate_read_throttle_and_display_spend covers the owner-gate, the once/day read throttle (no second read on re-call; a read outside the window still throttled), and that the function does not spend _login_warn_last. Full suite 294 passed; ruff clean; restarted + Run polling.
<!-- SECTION:NOTES:END -->
