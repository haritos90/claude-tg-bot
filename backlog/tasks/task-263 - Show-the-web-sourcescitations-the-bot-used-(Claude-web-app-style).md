---
id: TASK-263
title: "Show the web sources/citations the bot used (Claude-web-app style)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 263
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Show the web sources/citations the bot used (Claude-web-app style)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Won't do — superseded by the animated 🔎 thinking-tag search indicator (#319/#321): during a web search the `<tg-thinking>` draft rotates a search-themed gerund subset (🔎), which reads as "researching the web" more cleanly in Telegram than a post-answer sources footnote — and the model already cites its real sources as links in its answer. A separate "Sources" card was tried and removed in #321 as clutter.
<!-- SECTION:NOTES:END -->

