---
id: TASK-129
title: "Full per-session Tools page (toggle every tool on/off)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 129
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Configure each session's tools from Telegram.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`engine.tools_enabled`/`_resolve_tools` + `CHAT_TOOLS` (replaced the `web_search` bool); `db.threads.tools_enabled` (NULL=default, `[]`=tool-free); `sessions` rebuild-on-change wiring; `/tools` + `/settings → 🧰 Tools` with ✅/⬜ toggles (chat = web tools, code = full toolset, dangerous ones still gated). MCP connectors out of scope (#62/#119).
<!-- SECTION:NOTES:END -->

