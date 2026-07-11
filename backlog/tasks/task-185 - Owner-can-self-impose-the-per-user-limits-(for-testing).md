---
id: TASK-185
title: "Owner can self-impose the per-user limits (for testing)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - settings
dependencies: []
ordinal: 185
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
You can now apply the same limits to yourself — daily/weekly token caps, max-effort, and a tool cap — from your own user card (👑 on /users), to see how they behave before setting them on others. Clear them anytime to go back to uncapped.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The owner was hardcoded uncapped in every allowlist getter, so it could never self-test the per-user caps. Extended the existing `_owner_prefs` map (already backing the owner's `global_memory`) to also hold `rate` / `allow_max_effort` / `tool_cap`: `_norm_owner_prefs` normalises them (defaults uncapped / max-allowed / no-cap, and a legacy prefs blob upgrades transparently on load); the three getters (`rate_of` / `allow_max_effort_of` / `tool_cap_of`) + `describe` read them for the owner; the three setters (`set_rate` / `set_allow_max_effort` / `set_tool_cap`) store them. Removed the two EXTRA max-effort owner bypasses (`_may_max_effort`, the effort-tap gate, and `sessions`'s `is_owner or …`) so a self-revoke actually downgrades the owner — the getter still defaults the owner to allowed, so default behaviour is unchanged. The owner card now shows the max-effort / tools / day / week / clear-limits buttons (still no level/expiry/access/name/remove) and the tool-cap sub-page is unlocked for the owner. Enforcement is automatic via the existing by-uid `_access_block` + effort/tool resolvers; rate caps fire on the owner's own DM turns (usage attributes by `threads.chat_id == owner_id`). Lockout-safe: the gate covers turns, NOT commands, so the owner can always re-open the card to clear a self-cap. +5 tests, 122 green.
<!-- SECTION:NOTES:END -->

