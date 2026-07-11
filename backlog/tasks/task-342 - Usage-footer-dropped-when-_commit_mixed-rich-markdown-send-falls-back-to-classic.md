---
id: TASK-342
title: "Usage footer dropped when `_commit_mixed` rich-markdown send falls back to classic HTML"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 342
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Usage footer dropped when `_commit_mixed` rich-markdown send falls back to classic HTML
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
In `streamer._commit_mixed` the markdown branch appends the usage footer to `md`, but the rich-send `except` re-rendered `markup.md_to_html(seg)` — `seg` WITHOUT the footer — so a `SendRichMessage` failure lost the footer (it lived only on `md`, and `want_footer` was already cleared). The fallback now renders `md` (footer-bearing); the old `seg` call is kept commented with the #342 ref. Latent — only the footer is lost, and only when the rich send throws. compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

