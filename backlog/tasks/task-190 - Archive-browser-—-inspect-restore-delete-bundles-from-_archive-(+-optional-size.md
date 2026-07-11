---
id: TASK-190
title: "Archive browser — inspect / restore / delete bundles from `_archive/` (+ optional size cap)"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 190
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P2 · Effort S · deferred._

Lower-priority polish on cold storage. Retention / auto-purge already shipped (#178: `archive.purge_expired` + the daily loop + the owner retention picker). Revive to add (1) an optional SIZE cap (keep the archive dir under N MB, oldest-first) layered on the age purge, and (2) an owner-facing browser (under `/sessions` or a new `/archive`) listing archived sessions from the `.json` sidecars, RESTORING one (un-tar back to a fresh session) and DELETING one for good. Owner-only.
<!-- SECTION:DESCRIPTION:END -->

