---
id: TASK-138
title: "Unified settings schema (registry + resolver + 3-tier scopes + generic /settings)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 138
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every setting defined in ONE place with clear scopes/defaults/visibility; sandbox scope no longer confusing.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `settings_schema.py`: a frozen `Setting` registry (key·type·choices·default·scopes·view_role·edit_role·name_key + per-scope get/set adapters over EXISTING storage, zero data migration) + `Scope`(SESSION→USER→GLOBAL) / `Role`(GUEST<CHAT<CODE<OWNER) enums + `resolve()`/`resolve_from()` (precedence walk). Added the missing USER-default tier (`db.get/set_user_default` over kv). Role matrix (see memory): session+my-default editable by all roles for their own; global owner-only; sandbox/global-memory/default-model/access/caps owner-only & HIDDEN. Generic registry-driven `/settings` hub with 3 scope tabs, role-gated visibility, server-side edit_role re-check on apply (button≠auth — security-reviewed PASS), picker for choices (#101). Sandbox routed through the resolver (inversion hidden in adapter; equality unit-test vs old `sandbox_code and not no_sandbox`) so its scope is finally clear ("Sandbox: on · global default"). Review-fixes: per-tab value shows that scope's contribution via `resolve_from` (not cross-scope resolve); `edit_role>=view_role` asserted at import; dedicated `settings.row_maxturns` label (was duplicating "Model"). Tools-grid + users-admin stay bespoke pages, linked from the hub. +8 tests.
<!-- SECTION:NOTES:END -->

