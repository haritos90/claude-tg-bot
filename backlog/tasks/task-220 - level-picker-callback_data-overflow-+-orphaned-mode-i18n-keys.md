---
id: TASK-220
title: "/level picker callback_data overflow + orphaned /mode i18n keys"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 220
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/level picker callback_data overflow + orphaned /mode i18n keys
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
(a) The #216 `setlvl:` picker round-tripped the free-text target through `callback_data` (`setlvl:<target>:<level>`, parsed by `:`); a target containing `:` corrupted the split and an over-long handle overflowed Telegram's 64-byte cap. `_do_level` now rejects such a target as not-found before building the button (the full `<user> chat|code` form is unaffected). (b) Removed the dead `mode.show` / `mode.hint_upgrade` / `mode.hint_downgrade` i18n keys, orphaned when #218 made /mode toggle directly. py_compile + import + pytest + ruff.
<!-- SECTION:NOTES:END -->

