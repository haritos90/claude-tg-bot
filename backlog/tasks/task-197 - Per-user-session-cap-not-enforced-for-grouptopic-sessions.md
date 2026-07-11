---
id: TASK-197
title: "Per-user session cap not enforced for group/topic sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 197
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
No change — the per-user session limit applies to your private (DM) sessions; group-topic sessions are a shared group resource and are not counted.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
By design — not a gap. The cap is a per-USER limit and `_session_limit_block` counts `db.browse_threads(uid)`, i.e. threads keyed by the user's id (their DM surface). Supergroup forum-topic sessions are keyed by the GROUP's chat_id (a shared group resource, not a per-user session), so they are outside the per-user cap by construction; the non-private `_do_new` branch deliberately does not call the check. Documented the intent in `_session_limit_block`'s docstring and at the forum-topic create branch. No behavior change. py_compile + import + ruff clean; suite 173 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

