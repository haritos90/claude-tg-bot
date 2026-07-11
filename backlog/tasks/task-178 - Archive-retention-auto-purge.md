---
id: TASK-178
title: "Archive retention / auto-purge"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 178
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Old deleted-session archives are auto-removed after 6 months (owner-configurable in Settings → Admin, or set Never); nothing else changes.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Shipped the retention half of #177's follow-up: `archive.purge_expired(base, max_age_days)` deletes `_archive` bundles (+ their `.json` sidecars) older than the retention, run once at startup + daily by `sessions._archive_purge_loop` (`start_archive_purger`; cancelled in `aclose`). The period is owner-set from `/settings → 👑 Admin → 🗄 Archive retention` (1 / 3 / 6 / 12 months or Never), persisted in kv `archive_retention_days`; the startup default is `config.archive_retention_days` (env `ARCHIVE_RETENTION_DAYS`, 180 d = 6 months). The new owner Admin sub-page also gathers the global toggles (code-split, working-plate) + user-management launchers (allow/deny/level/expire/limit/stats). +3 tests, 128 green, ruff clean, deployed. Browser/restore + size-cap split to #190.
<!-- SECTION:NOTES:END -->

