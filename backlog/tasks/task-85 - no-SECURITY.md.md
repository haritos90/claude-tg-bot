---
id: TASK-85
title: "no `SECURITY.md`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 85
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
no `SECURITY.md`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a security policy: private disclosure via GitHub advisory, what to include + redact, Scope, and In/Out-of-scope tailored to this bot (token/allowlist/session leakage, permission-gate bypass, `/cwd`+`/dirs` escape, allowlist-fail-open, `ANTHROPIC_API_KEY` paid-billing, isolation; upstream SDK/host out of scope).
<!-- SECTION:NOTES:END -->

