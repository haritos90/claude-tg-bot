---
id: TASK-303
title: "`/users` card: add a per-user tokens line beside units; drop the footer description"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 303
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner's Users list now shows each person's raw token usage (5h / week / total) right under their units, and the explanatory footer was removed for a cleaner card.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `/users` list (`_users_text`) showed each user's weighted-units window (`↳ units: 5h · week · total`) only. Added a same-format RAW-tokens line directly below it (`↳ tokens: …`), fetched via a second `db.get_all_users_breakdown("raw")` GROUP BY alongside the existing `"units"` one; `_usage_line` became `_usage_lines` returning both lines (each omitted when that user has no rows for the metric) and the owner + per-entry call sites switched to `lines.extend`. New i18n key `users.entry_usage_tok` (en + ru). Removed the trailing description footer — the `users.footnote` ("Numeric ids are authoritative…") and `users.tap_hint` ("Tap a user to manage…") lines — since the card is self-explanatory and the extra tokens line made the prose redundant; both keys are kept (unused) for an easy revert. py_compile + import + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

