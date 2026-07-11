---
id: TASK-112
title: "Export code-session working-directory files (.zip)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 112
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Pull a code session's files out as a zip.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `/export` (code sessions only) + an 📦 Export-files button in the `/sessions` options menu: zips the session's workdir (`_workdir_zip`, in-memory `ZIP_DEFLATED`, capped ~49 MB) and sends it as a Telegram document. Distinct from `/history` (transcript export).
<!-- SECTION:NOTES:END -->

