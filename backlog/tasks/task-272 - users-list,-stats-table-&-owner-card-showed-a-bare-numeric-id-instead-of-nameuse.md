---
id: TASK-272
title: "`/users` list, stats table & owner card showed a bare numeric id instead of name/username"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 272
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The user list, statistics table, and your own (owner) card now show people by name and @username instead of a bare numeric id, and you can give yourself a friendly name.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `/users` list led each row with `<code>{id}</code>` and the stats table / owner card showed only the id for the OWNER (the owner is synthesised, never an access entry, so their username was unknown). Reworked the display to lead with the owner-assigned friendly name then `@username`, dropping the id from the list (it stays on the per-user card). Added owner identity storage: `allowlist` owner_prefs now carries `username` (auto-captured cheaply via `note_owner_identity` whenever the owner opens an owner-only screen — `/users`, `/userstats`, any `usr:` card tap) and `friendly_name` (the owner can now set their own via a new name button on the owner card; `set_friendly_name` special-cases the owner). `describe(owner)` surfaces both. New shared `_who_label` (HTML, list) + a plain variant (the escaped stats table) build "name @username", falling back to the id only when an entry has neither. `users.entry`/`users.pending`/`users.owner_id` now take a single `{who}` placeholder; the stats table resolves the owner from owner_prefs. +test (capture is idempotent + non-owner-ignored, owner friendly name set/clear, persists across reload). py_compile + import + ruff + i18n parity clean; suite 216 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

