---
id: TASK-168
title: "Wire `auto_compact` to real SDK compaction"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 168
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Auto-compaction is on by default; the owner can let specific users turn it off.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Forced ON by default (the CLI default) but DISABLEABLE when the owner delegates it. `engine._build_env` sets `DISABLE_AUTO_COMPACT=1` when the effective toggle is off (verified live: flips `ContextUsageResponse.isAutoCompactEnabled` True→False); forwarded through the sandbox `--clearenv` (`deploy/sandbox-claude.sh`). Setting moved to USER-scope (a per-session bool column defaults off and would wrongly override the forced-on default). Resolved in `_effective_settings` + rebuild-detected.
<!-- SECTION:NOTES:END -->

