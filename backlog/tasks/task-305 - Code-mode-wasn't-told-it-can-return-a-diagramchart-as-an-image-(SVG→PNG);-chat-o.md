---
id: TASK-305
title: "Code mode wasn't told it can return a diagram/chart as an image (SVG→PNG); chat-only"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 305
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions can now return diagrams/charts as images (emit an SVG block) just like chat, and both modes are told they can.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The streamer rasterizes any ` ```svg ` block to a PNG regardless of session mode (it has no mode-awareness), but only `CHAT_SYSTEM_PROMPT` told the model about it — code sessions (which get the `claude_code` preset + the shared self-description, not the chat prompt) were never informed they could return a diagram as an image, and the canonical self-description omitted SVG entirely. Added the SVG/diagram capability — the ` ```svg `→PNG path, the diagram-type list, and node-and-arrow layout guidance — to the shared `agent_context.md` Rendering section (appended to BOTH modes), plus a note that code mode may alternatively render an image file into `outbox/` (matplotlib/graphviz), and documented the auto long-reply→`response.md` delivery. Commented out the now-redundant SVG block in `CHAT_SYSTEM_PROMPT` (chat still receives it via the shared doc). compile + import + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

