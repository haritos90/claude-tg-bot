---
id: TASK-169
title: "Whole reply as ONE rich message — no splitting"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 169
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replies are never chopped into pieces — one richly-formatted message, long ones collapsed behind "show more".
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`streamer._commit_rich_markdown` sends the entire reply via `sendRichMessage({"markdown": …})`: the model's headings / lists / tables / code render natively, with **no char-limit split and no separate table bubbles**. Verified a 9.3k-char message renders with a "show more" button (~22 paragraphs) — so nothing needs splitting; the legacy chunk/split/table-bubble path is kept ONLY as the fallback (rich send fails). The `.md`-doc path is the last-resort size fallback. Every reply now uses the (slightly larger) rich font — consistent, and the reason owner-sent messages looked bigger than the bot's.
<!-- SECTION:NOTES:END -->

