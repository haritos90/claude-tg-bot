---
id: TASK-262
title: "Show which tool is running (incl. web search) in chat, not a bare \"thinking\""
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 262
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
While the bot searches the web (or uses any tool) in a chat session, you now see what it's doing ("🌐 Searching the web…") instead of a blank "thinking".
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The live tool-phase indicator (`tool_phase_label` → `streamer.set_phase`, shown in the `<tg-thinking>` block: "🌐 Searching the web…", "📖 Reading a page…", "⚙️ Running …") was gated to code mode, so a chat-mode web search looked like a generic "thinking" and the user couldn't tell anything was happening (just waiting). `sessions._run_one`'s `tool` branch now calls `set_phase` for ALL modes (chat is web-capable since #129); the code-only part is just the bubble-split (`segment_break`), which chat doesn't do. Renders only on the DM draft path (a no-op elsewhere). +test (chat WebSearch event → a "web" phase, no bubble split). py_compile + import + ruff + i18n parity clean; suite 211 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

