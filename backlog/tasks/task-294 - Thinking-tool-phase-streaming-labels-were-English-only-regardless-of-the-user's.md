---
id: TASK-294
title: "Thinking / tool-phase streaming labels were English-only regardless of the user's language"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 294
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "thinking…" animation and the live "reading/searching/running" tool labels now show in the user's own language (e.g. Russian), not always English.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The animated `<tg-thinking>` placeholder gerunds ("Thinking…", "Pondering…", …) and the live tool-phase labels ("📖 Reading …", "🌐 Searching the web…", "⚙️ Running …") were hardcoded English, so a Russian-language user saw English tags. The gerund rotation moved to i18n (`stream.thinking_words`, split from a comma list), the static placeholder to `stream.thinking`, and the tool-phase verbs to `stream.verb_*` (emoji stays in code). `tool_phase_label` and `_thinking_label` now take a `lang`; the streamer resolves it from the chat (`i18n.cached_lang`) via the new `Streamer.set_tool_phase`, and the gerund/placeholder render in the user's language. py_compile + import + ruff + i18n parity clean; suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

