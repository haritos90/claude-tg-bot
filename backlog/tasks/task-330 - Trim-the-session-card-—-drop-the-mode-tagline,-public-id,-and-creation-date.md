---
id: TASK-330
title: "Trim the session card — drop the mode tagline, public id, and creation date"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 330
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The session card is cleaner — it no longer repeats the chat/code description or shows the internal session id and creation date; just the name, the action menu, and the model.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The per-session card (`_session_card`) and the `/sessions` options ("choose an action") menu (`_session_options`) dropped two redundant lines: the mode **tagline** (e.g. "Chat — a plain, tool-free conversation…" / "Code — a Claude Code agent…") and the `{sid}` + `{date}` from `session.card_meta`, which now renders just `Model: <model>` in both locales. The mode glyph (💬 chat / 🟩 code) already tells the type apart, and the opaque public id + creation date were card noise. Removed the `mode_tagline(...)` line and the `sid=`/`date=` args from both call sites (old code commented with the ref); simplified the shared `session.card_meta` template. `_fmt_date` is left defined (now unused; cheap to re-wire). compile + import + ruff + suite 247 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

