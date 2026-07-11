---
id: TASK-353
title: "Section headings rendered in Telegram's separate heading font, clashing with the body font (\"jumping fonts\")"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 353
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Section headings in replies now use the same font as the body text (just bold) instead of Telegram's separate, larger heading font that some found jarring — so a reply reads as one consistent typeface, with a blank line kept above each heading so sections stay easy to scan. Whether a heading gets a leading emoji is still up to the assistant.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A markdown heading (`## `) in the rich `{"markdown"}` reply is parsed by Telegram as a heading BLOCK and painted in the client's own heading typography — larger/heavier, and a visually distinct face on some clients — so it read as a different FONT next to the body paragraph font (feedback: the heading font clashed / "jumped"). The streamer forwards the model's markdown verbatim on both the draft and the final send, so those headings reached Telegram raw; the classic-HTML fallback already demoted `##`→`<b>` (`md_to_html` step 3c), so the clash was rich-path-only. New `markup.demote_headings` rewrites each ATX heading (`# `..`###### `) to `**bold**` so the whole reply stays in ONE (body) font, headings just bold — wired into the draft frontier and BOTH rich-markdown commit paths (`_commit_rich_markdown` + the kept-but-uncalled `_commit_mixed`) so the draft and final bubble stay consistent (#237). The transform is line-local and SKIPS fenced code (a `# comment` inside a ``` / ~~~ block is untouched) and adds NO decoration — whatever leading emoji the model put on the heading is preserved verbatim, so the per-heading emoji choice stays the model's; a heading still being typed at the frontier renders as a complete early-closed bold span (no heading-font flash that snaps to bold). Because a lone bold paragraph gets only a SMALL inter-paragraph margin where a heading BLOCK had a larger one, a non-breaking-space (U+00A0) SPACER paragraph is inserted above each demoted heading to restore the vertical gap (the on-device "V2" choice; skipped for a first-line heading). On-device verified end-to-end: font unified AND spacing restored. Docs updated: markup.md (heading-demote note + §4 catalog row + §5 file-map row) and rich-message-spec.md (mapping bullet + the paragraph-vertical-margin finding). compile + import + ruff + suite 263 green (+focused tests: each ATX level→bold, emoji preserved, body/inline-bold untouched, `#nospace`/mid-line `#` ignored, fence skip for ``` and ~~~, demote-after-closed-fence, inner `**` dropped, partial-frontier→bold, spacer-above-a-following-heading + none-for-a-first-line heading, no-op); live restart "Run polling".
<!-- SECTION:NOTES:END -->

