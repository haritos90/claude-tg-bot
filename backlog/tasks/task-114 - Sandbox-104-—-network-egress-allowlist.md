---
id: TASK-114
title: "Sandbox #104 — network egress allowlist"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 114
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sandbox #104 — network egress allowlist
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
**Superseded by #119.** Necessary but not sufficient on its own: while the subscription token lives inside the jail it leaks via the bot's own output channel (agent reads it, the bot streams it to the user) and via any allowed data-store (e.g. GitHub) — so a firewall alone can't protect it. Egress was folded into the e2e design (#119), whose credential-broker removes the token from the jail entirely; the A–E egress-mechanism analysis lives on in #119's Details (component 2).
<!-- SECTION:NOTES:END -->

