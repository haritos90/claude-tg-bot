---
id: TASK-283
title: "Code-only commands gated on session MODE only, not the user's LEVEL (demotion gap)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 283
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code-only features (shell, secrets, tool policy) now check that YOU have code access — not just that the session happens to be a code one — so a user whose code access was revoked can't keep using them on an old session.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A full parallel audit of the permission model (owner / code / chat) across every command, callback, keyboard and the command menu found the owner-admin surface and the keyboard surface fully correct (server-gated AND UI-gated; the #277 invite/grant flow is owner-only on both axes), with ONE systemic gap: `/shell`, `/secret`, `/permissions` and the settings-hub Tools/Secret rows gated only on `session.mode == "code"`, never on the caller's allowlist LEVEL. Since demoting a user (`set_level` → chat) does NOT downgrade their existing code-mode sessions, a demoted user could still toggle shell mode, store secrets, or change the tool policy on a session they already owned (bounded — the per-turn `_access_block` already blocks the actual model/command turn, but the side-effecting commands ran without it). Added `_has_code_access(uid, uname)` (owner or level=="code") and gated all of them on it (command + the `sx:secret`/`sx:tools`/`tooltog` callbacks), and hid the hub Tools/Secret rows unless `role >= Role.CODE` — so a non-code user neither sees nor can use them, regardless of a session's mode. py_compile + import + ruff clean; suite 226 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

