---
id: TASK-182
title: "Per-user idle-TTL via the user card (incl. owner self)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - settings
dependencies: []
ordinal: 182
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner can set the idle-unload timeout per user — and on themselves (e.g. ∞ on a big-RAM box so sessions never unload) — from the user card.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The reaper's idle-TTL was a single global (#179). Now per-user: a `⏳ Idle` button on EVERY user card — including the owner's own card (reachable via the 👑 owner button on /users) — → arg-capture (minutes, `off`=∞/never, `default`=server default) → stored in the per-uid KV `idle_ttl_min` (works for any uid, owner included; no allowlist entry needed). `sessions._resolve_idle_ttl` reads it for the session OWNER and stamps `rec.idle_ttl` on each build; `_reap_once` honours the per-record value (≤0 = never reaped on idle; the RAM cap still applies as the hard safety). Hardcoded default 5→6 min. +1 test, 117 green.
<!-- SECTION:NOTES:END -->

