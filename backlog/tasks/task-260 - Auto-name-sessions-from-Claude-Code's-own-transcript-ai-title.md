---
id: TASK-260
title: "Auto-name sessions from Claude Code's own transcript ai-title"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 260
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sessions now name themselves automatically from the conversation topic (matching the title Claude Code shows in the browser); a manual rename still wins and is never overwritten.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Claude Code writes its auto-generated session title into the transcript JSONL as `{"type":"ai-title","aiTitle":…}` (the same label shown in the browser). `sessions._read_ai_title(cwd, session_id)` reads the LAST such line (it is rewritten as the topic evolves) from `<sid>/state/<encoded-cwd>/<session_id>.jsonl` — cheap, JSON-parsing only the rare ai-title lines, capped at 64 chars. After each turn `_run_one` adopts it as the session label (`db.set_session_name(..., manual=False)`) only when it changed, so `/sessions` shows meaningful names with no user action. A new `name_auto` column (default 1) gates this: a manual `/rename` pins the name and clears the flag (`set_session_name(..., manual=True)` → `name = ?, name_auto = 0`), after which the auto-namer is a SQL no-op — a hand-chosen label is never clobbered. `_ThreadRecord` mirrors `name`/`name_auto` (re-synced each `_ensure`) for the change-detection. The title follows the conversation language (a user-facing DM label, not a committed artifact). +5 tests (read last/cap, missing→None, e2e adopt, pinned-skip, db manual/auto pin). py_compile + import + ruff clean; suite 204 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

