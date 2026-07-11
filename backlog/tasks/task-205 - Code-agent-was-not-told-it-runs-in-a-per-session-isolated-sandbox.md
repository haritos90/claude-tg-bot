---
id: TASK-205
title: "Code agent was not told it runs in a per-session isolated sandbox"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 205
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In a code session the agent now knows it runs in an isolated per-session sandbox and explains this correctly if asked.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `engine.ISOLATION_NOTE`, appended to the code-mode system-prompt preset alongside `OUTBOX_INSTRUCTION`, so the agent can accurately answer the user about privacy / where files live / whether others can see them. The per-session-private workdir claim is always true (#181); filesystem confinement and the network allowlist are hedged ("may be") since they depend on the sandbox layers (#119/#180) being enabled. Deployed.
<!-- SECTION:NOTES:END -->

