---
id: TASK-118
title: "Owner-only per-session sandbox opt-out (run a code session raw)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 118
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner can run a code session with isolation OFF to A/B-test the sandbox vs a bot bug.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New owner-only `/sandbox on|off` (code sessions): `off` sets a per-session `no_sandbox` flag (new `threads` column + `db.set_no_sandbox`, migrated in) so THIS code session's claude runs WITHOUT the bubblewrap jail even when `SANDBOX_CODE` is on — to tell a sandbox issue apart from a bot bug; `on` re-isolates. The engine sandboxes a code session only when `settings.sandbox_code and not state.no_sandbox`; the flag is owner-set only (command is owner-gated), so guests can never escape. Rebuilds the session on change; in the owner's command menu.
<!-- SECTION:NOTES:END -->

