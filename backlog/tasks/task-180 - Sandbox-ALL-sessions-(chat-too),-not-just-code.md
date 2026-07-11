---
id: TASK-180
title: "Sandbox ALL sessions (chat too), not just code"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 180
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every session — chat and code, including the owner's — runs sandboxed (non-root, confined); nothing runs as host root.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat ran un-jailed as ROOT (only code was sandboxed). `engine._build_options` now routes the chat branch through `_enable_sandbox` and `_ensure_client` creates the jail state dir for ALL modes, so every session (chat + code, incl. the owner's) runs as unprivileged uid 65534, filesystem-confined to its workdir, root read-only, env wiped. Chat stays tool-free — the win is non-root + workdir confinement + the transcript off the host. Dropped the `/sandbox` code-only gate (`handlers.cmd_sandbox`). menu.md + README updated. Verified live: all 6 sessions jailed.
<!-- SECTION:NOTES:END -->

