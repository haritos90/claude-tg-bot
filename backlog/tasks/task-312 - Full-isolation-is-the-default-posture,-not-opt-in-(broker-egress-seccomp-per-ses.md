---
id: TASK-312
title: "Full isolation is the default posture, not opt-in (broker / egress / seccomp / per-session uid default-on)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 312
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Out of the box the bot now runs with full session isolation — credential broker, loopback-only egress, seccomp denylist, and a per-session non-root uid — instead of leaving those off until explicitly enabled.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The four isolation layers now default ON in `config.py` (`CRED_BROKER`, `SANDBOX_EGRESS`, `SANDBOX_SECCOMP`, `SANDBOX_PER_SESSION_UID`; the old opt-in defaults kept commented with a ref) — a host that cannot support a layer opts OUT via its env flag (`=0`). README + `isolation.md` reframed to match: `bubblewrap` is a required dependency (not optional), the sandbox is mandatory for every session, full isolation is on by default rather than opt-in, and the env-flag table shows the new `1` defaults plus each layer's prerequisite. Runtime no-op on a deployment that already sets the flags in `.env`. compile + import + ruff + suite 230 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

