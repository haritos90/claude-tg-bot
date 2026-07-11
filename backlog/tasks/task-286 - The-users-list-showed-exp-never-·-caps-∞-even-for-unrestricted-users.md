---
id: TASK-286
title: "The /users list showed \"exp: never · caps: ∞\" even for unrestricted users"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 286
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The user list no longer clutters every unrestricted user with "exp: never · caps: ∞" — those only appear when the user is actually time-limited or capped.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Each user row always rendered `· exp: {expiry} · caps: {quota}`, so a never-expiring, uncapped user showed noisy "exp: never · caps: ∞". The exp and caps segments now fold into a `{meta}` placeholder built by `_user_meta`, which includes "exp" ONLY when the user actually has an expiry and "caps" ONLY when actually rate-capped — an unrestricted user shows just "• {name} — chat". `users.entry`/`users.pending` take `{meta}`; new `users.meta_exp`/`users.meta_caps` strings. py_compile + i18n parity clean; suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

