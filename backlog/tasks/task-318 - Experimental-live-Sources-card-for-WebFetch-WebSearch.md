---
id: TASK-318
title: "Experimental: live \"Sources\" card for WebFetch / WebSearch"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 318
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Web research now shows a tidy, live-updating list of the pages and searches the bot is using to answer — so you can see where the info comes from.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
When the agent uses WebFetch or WebSearch (chat AND code), a SEPARATE rich message now lists the resources it is pulling from — WebFetch URLs (🔗, scheme + trailing slash trimmed) and WebSearch queries (🔍) — rendered as inline code and edited in place as more arrive (`streamer.sources_card_markdown` + `add_web_source`, mirroring the TodoWrite card: deduped, capped at 15, persists across segment breaks, best-effort). Wired from the `tool` branch of the stream loop, pulling `url`/`query` from `tool_input`. Experimental ("does it look OK"), easily gated/reverted. +pure render test + a wiring test. compile + import + ruff + suite 234 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

