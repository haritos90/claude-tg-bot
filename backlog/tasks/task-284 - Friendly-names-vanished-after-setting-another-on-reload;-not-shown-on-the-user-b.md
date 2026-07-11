---
id: TASK-284
title: "Friendly names vanished after setting another / on reload; not shown on the user buttons"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - bug
dependencies: []
ordinal: 284
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Friendly names you assign in /users now STICK (they were being silently wiped when you named the next user or on any reload) and show on the tappable user buttons too — not just in the text list.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two parts. (1) DATA-LOSS bug: `allowlist._norm_record` / `_norm_pending` (which `_load` runs over every entry/pending on each disk reload) did NOT carry `friendly_name`, so the first reload after setting one wiped ALL friendly names — assigning a name to user B (or any reload triggered by another user's message / restart) erased user A's. Both normalizers now preserve it (shared `_norm_friendly` helper, trimmed/capped); +regression test (set on two users + a pending one, reload, all survive). (2) UX: the per-user tappable buttons in `/users` (`_users_keyboard`) ignored the friendly name — they now prefer it (then `@username`, then id; pending likewise via a `{who}` placeholder), matching the text list + stats (#272). py_compile + import + ruff + i18n parity clean; suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

