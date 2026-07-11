---
id: TASK-307
title: "Sessions browser: collapse stray empty untitled sessions, merge pager into the New-chat row, monospace stats"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 307
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The session list no longer fills up with empty "Not named yet" sessions, pages with ◂/▸ on the New-chat row, and shows aligned msgs/tokens/units per session for easy comparison.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Four `/sessions`-browser changes. (1) AT MOST ONE empty untitled session per user: idle rotation (#266/#271), the New-chat button, and opening `/sessions` after an idle gap could each leave an abandoned placeholder behind, so several accumulated. New `_gc_untitled_empties(uid, keep)` deletes every DM session that is unused (zero requests) AND never manually renamed (`name_auto`) AND not a favorite, except the current/target — run on every DM `/sessions` render and on switch; the cap-evictor and the GC now share a `_dispose_session` helper, so a used or renamed session is never touched. (2) Renamed the empty-session placeholder from "Untitled" to "Not named yet" (`session.default_name_chat`/`_code`, `session.first_default`; the `ru` translation updated alongside). (3) Merged the pager (◂ / ▸) into the New-chat row (page 1 shows only ▸) and RETIRED the "New code" browser button — a session is born a chat and promoted with `/code`. (4) The per-row stats line is now monospace + compact (msgs / tokens / weighted-units), NBSP-padded so columns align vertically across rows; `get_usage_totals_bulk` now also returns weighted units and `browse_threads` returns `name_auto`. compile + import + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

