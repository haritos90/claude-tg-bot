---
id: TASK-255
title: "Scheduled prompts bypass the live allowlist gate (revoked user keeps firing)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 255
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A scheduled task stops running once its owner loses access, instead of continuing in the background.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`sessions._fire_schedule` now re-checks `self.allowlist.is_allowed(owner_uid, None)` before dispatching; a schedule whose owner is no longer allowlisted is disabled with `last_status="revoked"` instead of firing. The scheduler bypassed `AllowlistMiddleware` by calling `handle_text` directly, so a schedule created while allowed kept consuming the subscription after the owner was removed/expired. (Mode/level was never an escalation path — re-resolved from the owner's persisted state.) +test. py_compile + import + ruff clean; suite 197 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

