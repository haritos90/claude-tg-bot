---
id: TASK-360
title: "Demoted headings were set off only ABOVE; add a symmetric gap BELOW"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 360
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Section headings in replies are now set off by a blank gap both above and below the (bold) heading, so sections stand out instead of the heading sitting flush against the text beneath it.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #353 rich-path heading demotion (`markup.demote_headings`, ATX → `**bold**`) inserted a `U+00A0` spacer paragraph only ABOVE each demoted heading, so a heading had a gap on top but butted against the body text below. Now a deduped spacer is placed ABOVE **and** BELOW each heading via a shared `_add_spacer()` helper: the ABOVE spacer is still skipped for a first-content heading (no blank line at the message top); the BELOW spacer is added LAZILY on the next line so it never trails the streaming frontier (a heading at the frontier shows no trailing gap until content follows); the spacer is a `U+00A0` paragraph because a blank line alone is trimmed by Telegram; and adjacent headings (no body between) share ONE gap (spacers never stack). Side benefit: a heading immediately followed by body with no blank line (`## H` then `body`) now also gets the BELOW spacer, so the heading paragraph never soft-break-joins onto the body line. compile + import + ruff + suite 266 green (test_demote_headings extended: both-sides spacer, lazy/no-trailing on a heading-last and at the frontier, first-content placement, adjacent-heading dedup, no-blank-after-heading); `docs/markup.md` + `docs/rich-message-spec.md` updated; live restart "Run polling".
<!-- SECTION:NOTES:END -->

