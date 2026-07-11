---
id: TASK-157
title: "Adopt Telegram's modern rich formatting in markup (strikethrough, spoiler, block quotes incl. expandable)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 157
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Claude's replies now use rich Telegram formatting — strikethrough, spoilers, and collapsible (expandable) block quotes; code blocks keep their one-tap copy.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup.md_to_html` now renders `~~strike~~`→`<s>`, double-pipe spoilers→`<tg-spoiler>` (conservative: requires non-space inner edges, so a spaced logical-or stays literal), and `> ` line-runs→`<blockquote>` with long runs (> `EXPANDABLE_BLOCKQUOTE_MIN_LINES`=10) collapsing to `<blockquote expandable>`; inline styles nest inside a quote, code/pre left untouched. Added README "Message formatting" section + Telegram doc links. +6 markup tests (74 total green); ruff clean. Owner picked collapse-long-quotes + spoiler-on via an in-bot preview + question.
<!-- SECTION:NOTES:END -->

