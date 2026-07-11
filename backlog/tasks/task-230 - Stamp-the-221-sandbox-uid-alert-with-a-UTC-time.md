---
id: TASK-230
title: "Stamp the #221 sandbox-uid alert with a UTC time"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 230
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The sandbox uid-isolation alert now shows the UTC time it was checked, so repeat alerts can be told apart and pinned to a restart.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The startup uid-doctor owner DM (`admin.uid_collision_alert`) had no timestamp, so a recurring alert (every restart re-runs the doctor over the same not-yet-self-healed workdirs) was indistinguishable from a genuinely new collision. Added a `{ts}` field — `datetime.now(timezone.utc)` formatted `YYYY-MM-DD HH:MM:SS UTC` — to the alert header (en + ru), computed in `bot.main` at send time. py_compile + i18n round-trip; live, polling.
<!-- SECTION:NOTES:END -->

