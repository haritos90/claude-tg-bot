---
id: TASK-290
title: "Harden request-grant & unknown-user-notice flow"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 290
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A stale "Allow" tap no longer changes an already-granted user's access level, and a username-only code user now sees the "New code" button they're allowed to use.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three hardening fixes on the #277 unknown-user notice + owner request-grant. (1) The `req:` Allow callback now checks `allowlist.level_of` first and, if the user is already allowed, edits the notice to an info message + toast instead of calling `add` — so a stale Allow tap can no longer silently re-set an existing user's level (e.g. demote code→chat); new `access.req_already`/`access.req_already_toast` strings. (2) `AllowlistMiddleware._notified` is now pruned (entries older than the throttle window dropped once it grows past 256) so it can't grow unbounded on a flood of distinct unknown ids. (3) the "New code" button hide in `_render_sessions` now routes through `_has_code_access(chat_id, uname)` with the tapper's username (threaded in), matching the `ses:new:code` callback gate, so a username-only code grant sees the button instead of it being hidden. py_compile + import + ruff + i18n parity clean; suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

