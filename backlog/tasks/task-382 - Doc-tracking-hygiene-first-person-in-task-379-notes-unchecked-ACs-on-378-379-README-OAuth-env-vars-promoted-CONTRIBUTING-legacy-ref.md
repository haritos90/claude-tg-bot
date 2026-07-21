---
id: TASK-382
title: >-
  Doc/tracking hygiene: first-person in task-379 notes, unchecked ACs on
  378/379, README OAuth env vars, promoted CONTRIBUTING legacy ref
status: Done
assignee: []
created_date: '2026-07-20 12:44'
updated_date: '2026-07-20 13:26'
labels:
  - docs
dependencies: []
priority: low
ordinal: 20362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Documentation and tracking cleanups found reviewing the token-refresh + docs-reorg batch (the token-batch counterpart of task-377 for the interleave batch).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 No first-person voice in task files; Done tasks carry no dangling unchecked acceptance criteria
- [x] #2 README documents the live token-refresh env vars
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Doc/tracking hygiene applied. task-379 notes: first-person 'our refresher' -> 'the refresher'. Tasks 378 and 379 (Done): all acceptance criteria checked off (satisfied in code). README.md: the OAuth token-refresh bullet now lists the live tunables (OAUTH_REFRESH, OAUTH_REFRESH_INTERVAL_SEC, OAUTH_REFRESH_SKEW_SEC, OAUTH_REFRESH_SWEEP_DEADLINE_SEC, OAUTH_REFRESH_HEARTBEAT_EVERY, LOGIN_EXPIRY_WARN_DAYS); the docs/ module-map row now includes troubleshooting.md and voice.md. CONTRIBUTING.md: the leaked #110/#118 pointer is replaced with a neutral statement of the comment-out pattern (the #120 code-comment example is left as it illustrates the convention).
<!-- SECTION:NOTES:END -->
