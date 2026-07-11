---
id: TASK-136
title: "Sessions/files UX cleanup + sandbox default-on with workdir-only writes"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 136
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
List/menu/files no longer leak ids or paths; code sessions are jailed by default and can only write inside their workdir.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
One batch: (1) `/sessions` list drops the `sid` public id — rows lead with icon + **name** only; (2) session options menu packs two-per-row (Transcript · Export files / Delete · Back) instead of one button per row; (3) the switch-card quick action relabeled Export→**Transcript** (same `ses:hist`) and the stale options menu is now deleted when you switch; (4) `/files` shows the session **name**, never the host path (`./workdirs/<id>` leaked the internal numbering + shared parent); export zip named by `sid` not the raw id; (5) **sandbox ON by default** (`SANDBOX_CODE=1`, was opt-in) + `base_workdir` resolved absolute (fixes `SBX_STATE` persistence) + `--remount-ro /` in `deploy/sandbox-claude.sh` so the jail root is read-only: a stray absolute write (e.g. the agent's imagined `/Users/<name>`) now FAILS LOUDLY and the agent retries in the cwd, instead of either polluting the host (un-jailed root) or silently vanishing into throwaway jail space. Verified: writes to workdir/`/tmp`/`HOME`/`~/.claude/projects` still work, `/Users` + `/root` blocked, nothing leaks to host. Removed the `/Users/haritos` host debris the un-jailed agent had created.
<!-- SECTION:NOTES:END -->

