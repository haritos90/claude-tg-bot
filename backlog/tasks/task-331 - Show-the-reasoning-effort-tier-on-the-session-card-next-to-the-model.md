---
id: TASK-331
title: "Show the reasoning-effort tier on the session card next to the model"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 331
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The session card now shows the reasoning-effort level (e.g. "Effort: high") right next to the model, so you can see at a glance how hard the session is set to think.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The session card (`_session_card`) and `/sessions` options menu (`_session_options`) meta line now renders `Model: <model> · Effort: <tier>`, the tier being the bare value (`low`/`medium`/`high`/`xhigh`/`max`). Reads the session's stored `st.effort`, falling back to `high` (the SDK default, per `effort.default_label`) when unset. Added a `{effort}` placeholder to the shared `session.card_meta` template (both locales) and pass `effort=st.effort or "high"` from both call sites. compile + import + ruff + suite green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

