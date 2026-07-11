---
id: TASK-191
title: "Proactive OAuth token refresh (stop the ~8h idle-expiry 401)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 191
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot now refreshes its subscription login automatically before it expires, so it no longer stops working after sitting idle (e.g. overnight) and needing a manual re-login.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The on-disk subscription OAuth access token has a hard ~8h life and nothing rotated it: the idle reaper kills the `claude` subprocess in ~6 min, but a freshly-spawned one just re-reads the SAME on-disk token, and the SDK does not auto-refresh under subscription auth — so a turn after a >8h idle gap (e.g. overnight) 401'd until a manual re-login. New `token_refresh.py` owns the OAuth `refresh_token → access_token` exchange (endpoint `platform.claude.com/v1/oauth/token` + the public Claude Code client id, both read from the bundled CLI) and rewrites `~/.claude/.credentials.json` ATOMICALLY (temp + `os.replace`, mode 0600, all other fields preserved). `SessionManager.start_token_refresher` runs a fail-soft loop (sweep every 30 min, renew when <1h of life remains; cancelled in `aclose`), wired in `bot.main` next to the usage poller / reaper. P0-safe: OAuth only (refresh token + client id) — never an `ANTHROPIC_API_KEY`, so billing stays on the subscription. Fail-soft: any error leaves the creds untouched → falls back to the engine 401 self-heal / manual re-login. Tunable via `OAUTH_REFRESH` (kill-switch), `OAUTH_REFRESH_INTERVAL_SEC`, `OAUTH_REFRESH_SKEW_SEC`. Verified live: a forced refresh rotated the token, moved `expiresAt` +8h, and the new token authenticated against the account usage endpoint. +5 tests, 134 green, ruff clean, deployed (loop logged at startup). A lighter standalone carve-out of #119's broker OAuth-refresh component.
<!-- SECTION:NOTES:END -->

