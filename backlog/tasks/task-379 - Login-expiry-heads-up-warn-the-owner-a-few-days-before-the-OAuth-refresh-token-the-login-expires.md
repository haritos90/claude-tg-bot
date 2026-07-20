---
id: TASK-379
title: >-
  Login-expiry heads-up: warn the owner a few days before the OAuth refresh
  token (the login) expires
status: Done
assignee: []
created_date: '2026-07-20 11:34'
labels:
  - reliability
  - auth
  - ux
dependencies: []
ordinal: 17362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The refresher (#191/#378) renews only the 8h access token; the OAuth *refresh* token (the login) has a hard ~monthly life (refreshTokenExpiresAt) and still needs a manual 'claude' re-login. Without a heads-up the owner only discovers this when the login expires and every turn starts failing. Warn a few days ahead so they re-login before an outage.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A localized one-line notice is shown when the login is within N days (default 3, LOGIN_EXPIRY_WARN_DAYS) of refreshTokenExpiresAt
- [ ] #2 Owner-only (only they can re-login on the host) and throttled to ~once/day; shown ABOVE the answer, never inside the <tg-thinking> draft; not written to history
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
token_refresh.py: login_seconds_left() reads claudeAiOauth.refreshTokenExpiresAt (epoch ms); login_warn_days() is a pure floor-to-days helper gated by LOGIN_EXPIRY_WARN_DAYS. sessions.py: SessionManager._login_expiry_banner() applies the owner gate + ~once/day in-memory throttle (self._login_warn_last) + i18n; the finalize path prepends it to a display_text passed to streamer.finish() while db.log_message() still logs the clean answer (banner is display-only). i18n key session.login_expiry_warn (en/ru, plain text so it rides the markdown render path; parity test green). Tests: login_seconds_left present/absent, login_warn_days threshold+floor. Full suite 288 passed; ruff clean; restarted + verified. Note: our refresher does not update refreshTokenExpiresAt, so the value reflects the last host 'claude' login; if the server ever rotates the refresh-token expiry the warning would fire early (safe), never late.
<!-- SECTION:NOTES:END -->
