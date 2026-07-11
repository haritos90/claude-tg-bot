---
id: TASK-319
title: "Web-research UX: animated search indicator + readable Sources card; animation constraints documented"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 319
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
While the bot searches the web you now see a live, animated "🔎 Searching…" indicator (with search-flavoured words) the whole time — not a frozen screen — and the list of sources it used renders cleanly, one per line.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Fixed the news-search UX (a server-side WebSearch showed no activity, and the Sources card ran every source onto one line). (1) The `<tg-thinking>` tag now ANIMATES during a search: a web search/fetch flips the streamer into "searching" mode (`_searching`) and the placeholder rotates a dedicated SEARCH-themed gerund subset (`stream.searching_words`, 🔎) instead of a static "Searching the web" phase (a fixed string doesn't animate — only a changing draft does). (2) A new `tool_start` engine event (emitted on the streaming `content_block_start` for a tool / server-tool block, defensively) surfaces the phase the MOMENT a search begins — the assembled `tool` event only fires AFTER a server-side search returns, which is why nothing showed during the wait. (3) The Sources card now renders each resource on its OWN line (markdown list — a single newline collapses in Telegram rich markdown) and flips from an in-progress "🔎 Searching…" header to "📚 Sources" at finish. (4) Documented the hard animation constraints in `rich-message-spec.md`: only a `<tg-thinking>` rich DRAFT animates; regular message edits are ~1/sec (fine for side info like the Sources/Todo cards, not for animation or text); when working and not streaming text, an animating thinking draft is mandatory. +tests (gerund parity for both subsets, search-mode routing, tool_start phase, sources render). compile + import + ruff + suite 236 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

