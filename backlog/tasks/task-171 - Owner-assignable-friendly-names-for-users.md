---
id: TASK-171
title: "Owner-assignable friendly names for users"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 171
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner can label each user with a friendly name, shown in the user card and the stats table.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`allowlist` entries gained `friendly_name` + `set_friendly_name` (clear with `-`/`off`); the user card has an ✏️ button → arg-capture (`usrname:<t>` → `_apply_user_value`); the name shows in the card title (`Name (@user)`) and is preferred in `/userstats`. Persists in `allowlist.json`. Unit-checked roundtrip.
<!-- SECTION:NOTES:END -->

