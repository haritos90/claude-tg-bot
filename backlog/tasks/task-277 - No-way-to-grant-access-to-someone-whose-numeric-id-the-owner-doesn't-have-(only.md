---
id: TASK-277
title: "No way to grant access to someone whose numeric id the owner doesn't have (only a phone/name)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 277
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
If you only have someone's phone or name (not their Telegram id), just have them open the bot and send a message — you'll get a request with their id and an Allow button, so you can grant access with one tap.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A Telegram bot can't look a user up by phone number, and an unknown user's messages were silently dropped — so to allowlist someone you needed their `@username` or numeric id up front. Now an UNKNOWN user's first text attempt notifies the OWNER (`AllowlistMiddleware._maybe_notify_owner`, throttled to one ping per user per 6h, sent SILENTLY via `disable_notification`) with their name + numeric id + two one-tap buttons (✅ Allow chat / ✅ Allow code); the owner taps and `on_access_request_cb` (`req:al`/`req:ac`) grants by id via `allowlist.add`. So the flow is: the person taps the bot and sends anything → the owner gets the request with their id → one tap allows them. The deny path is unchanged (the update is still dropped; the button only NOTIFIES — granting still requires the owner's tap). Middleware wired with `owner_id` in bot.py. +3 tests (drop+notify-once+throttle; allowed passes through; owner never self-notifies). py_compile + import + ruff + i18n parity clean; suite 223 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

