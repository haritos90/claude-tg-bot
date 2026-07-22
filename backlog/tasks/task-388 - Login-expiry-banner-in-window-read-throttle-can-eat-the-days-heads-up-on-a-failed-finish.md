---
id: TASK-388
title: >-
  Login-expiry banner: in-window read-throttle can eat the day's heads-up on a
  failed finish
status: Done
assignee: []
created_date: '2026-07-22 08:34'
updated_date: '2026-07-22 08:51'
labels:
  - reliability
dependencies: []
priority: medium
ordinal: 26362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner-only login-expiry heads-up must survive a failed delivery. The display throttle (_login_warn_last) is intentionally spent only after streamer.finish() delivers the banner (sessions.py:1641-1644), so a turn whose finish raises does not consume the day's nudge. The #384 read throttle (_login_check_last) breaks that guarantee in-window: _login_expiry_banner spends _login_check_last on any read that passes the gates, including an in-window read that returns a banner before delivery, so after a failed finish the next owner turn is gated to None for ~20h. Restore the invariant while keeping the outside-window once-per-turn read suppression.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 In the warn window, a banner that is computed but not yet delivered does not spend _login_check_last, so a failed finish() re-offers the heads-up on the next owner turn
- [ ] #2 Outside the warn window, the creds file is still read at most ~once per ~20h (the #384 goal preserved)
- [ ] #3 tests/test_sessions.py asserts the corrected in-window semantics (delivery spends the display throttle; an undelivered banner is re-offered) instead of the current swallow
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
sessions.py: _login_expiry_banner no longer spends _login_check_last on an in-window read that returns a banner — the read throttle is spent only in the days-is-None branch (nothing to show). Outside the warn window this still limits the creds read to ~once/day; in-window the display throttle (_login_warn_last, spent by the caller after finish() delivers) governs the cadence, so a failed finish re-offers the heads-up next turn. The old assignment is kept commented with a #388 ref. tests/test_sessions.py updated: the in-window assertions now verify the read throttle is NOT spent before delivery and an undelivered banner is re-offered (re-reads), delivery then gates via _login_warn_last, and outside-window a second turn does not re-read.
<!-- SECTION:NOTES:END -->
