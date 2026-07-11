---
id: TASK-89
title: "CI lacked least-privilege + concurrency"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - build
dependencies: []
ordinal: 89
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
CI lacked least-privilege + concurrency
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`.github/workflows/ci.yml` now sets `permissions: contents: read`, a `concurrency` group (`cancel-in-progress`), and `workflow_dispatch`.
<!-- SECTION:NOTES:END -->

