---
id: TASK-43
title: "math rendered as raw LaTeX in chat"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 43
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
math rendered as raw LaTeX in chat
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat system prompt now tells the model Telegram cannot render LaTeX — write plain Unicode (×, ≈, ², √, …), no `$…$` / `\frac` / `\text`. Robust render-time conversion tracked as #51. _**Superseded by #297**: Telegram (Bot API 10.1) now renders `$…$` / `$$…$$` math natively, so the prompt was flipped back to emit LaTeX._
<!-- SECTION:NOTES:END -->

