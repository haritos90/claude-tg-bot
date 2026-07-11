---
id: TASK-229
title: "Surface a code session's live task list in Telegram (rich to-do list)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 229
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions can show a live, self-updating checklist of the agent's task list (opt-in via /settings → Live task list).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The agent's `TodoWrite` tool events (already on the engine stream as `tool` events with `tool_input.todos`) are surfaced as a compact, live-updating card. `sessions._run_one` (code mode, toggle on) extracts the todos and calls `streamer.update_todo_card`, which sends ONE rich message on the first TodoWrite of a turn and EDITS it in place on later ones (a fresh Streamer per turn = one card per turn) — a SEPARATE bubble, off the draft typewriter path. `markup.summarize_todos` (pure, tested) renders `📋 {n} tasks ({done} done, {open} open)` + one glyph line per task (✅ done / 🔄 in-progress / ⬜ pending), content truncated for compactness. Delegated per-session+user bool `todo_card` (default OFF, CODE-only): new threads column + migration, `settings_schema` Setting (PAGE_ORDER + CODE_ONLY), `settings.row_todo_card` + `todo.card_header` i18n (en+ru). All sends best-effort (a failure never disturbs the answer). +4 markup tests. py_compile + import + i18n symmetry/placeholder parity + ruff clean; **full suite 177 passed**; live restart "Run polling"; migration verified (`todo_card` column added). On-device render of a real TodoWrite turn pending.
<!-- SECTION:NOTES:END -->

