---
id: TASK-37
title: "file attachments (images, PDF, text/code)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 37
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
file attachments (images, PDF, text/code)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Telegram photos, image files, PDFs, and UTF-8 text/code files are accepted: images/PDFs go to the model as Anthropic content blocks (image / `document`), text files are inlined into the prompt; caption = prompt; works in chat AND code mode. Generic `attachments` plumbing (engine `_send_query` → sessions queue → `run`). Caps: 5 MB image / 20 MB PDF / 1 MB text. Verified live with real image + PDF calls + plumbing tests. Albums arrive as separate turns (one per message).
<!-- SECTION:NOTES:END -->

