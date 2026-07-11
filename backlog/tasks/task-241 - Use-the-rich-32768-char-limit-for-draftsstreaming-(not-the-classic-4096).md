---
id: TASK-241
title: "Use the rich 32768-char limit for drafts/streaming (not the classic 4096)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 241
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Long replies now stream the whole growing text in the draft (not just the last ~3900 chars).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Rich messages allow 32768 chars vs the classic 4096, but the draft frontier was split at `markup.SAFE_LIMIT` (3900) so a long reply streamed only its ~3900-char tail. Added `markup.RICH_LIMIT = 32768`; `_render_draft` now splits the draft body at `RICH_LIMIT`, so a normal reply streams in FULL (one chunk) and only a >32768 reply tracks the tail. The rich final message (`_commit_rich_markdown`) already sent the whole reply as one bubble; the classic 4096 split / `.md`-document fallback stays only on the failure path. py_compile + ruff + suite (163) clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

