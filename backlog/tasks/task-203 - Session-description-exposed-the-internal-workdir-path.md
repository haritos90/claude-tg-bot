---
id: TASK-203
title: "Session description exposed the internal workdir path"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 203
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Session cards no longer show the internal working-directory path.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The session card / options card / mode taglines printed a terminal-style `…/work $` line built from `mode_tagline(cwd=…)`. The path is an internal detail the user never interacts with, so the `tagline_where` append was removed from `mode_tagline` (old line kept commented per the audit convention; `cwd` stays in the signature for callers). Deployed.
<!-- SECTION:NOTES:END -->

