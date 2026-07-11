---
id: TASK-181
title: "Nest session files under one parent — `<sid>/{work,state}`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 181
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Everything for a session lives in one `workdirs/<sid>/` folder; nothing outside it; deleting archives that one folder.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Files were split across `<sid>` (work) + `<sid>.sbxstate` (state) siblings, plus a host transcript in `~/.claude/projects` for un-jailed sessions — three places. Now ONE parent `BASE_WORKDIR/<sid>/{work,state}`: cwd = `work/` (bound into the jail, writable); the transcript/HOME = sibling `state/` (NOT bound, so the agent can't reach it). Updated `_default_cwd` / `allocate_dm_session` / handlers `_workdir_zip`+default_cwd / `engine.SBX_STATE`+`_ensure_client`; `archive.py` bundles the whole `<sid>/`; retired the legacy `migrate_workdirs_to_sid` (its basename==sid skip-check would strip the new `/work` every startup). The 6 live sessions migrated BY HAND (dirs restructured, host/sbxstate transcripts moved into `state/` + renamed to the new cwd-encoding so `resume` survives, DB cwds bumped) after a full backup; verified no bot files remain outside `workdirs/`. Tests updated, 116 green.
<!-- SECTION:NOTES:END -->

