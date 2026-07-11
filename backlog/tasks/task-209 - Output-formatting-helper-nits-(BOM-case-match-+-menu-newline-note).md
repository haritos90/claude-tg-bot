---
id: TASK-209
title: "Output-formatting helper nits (BOM case-match + menu newline note)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 209
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Output-formatting helper nits (BOM case-match + menu newline note)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup.as_document` now matches the `.md`/`.txt` extension case-insensitively, mirroring `ensure_text_bom` (#206), so a `.MD`/`.TXT` is BOM'd identically by the long-reply and outbox paths. Added a note on `handlers._send_menu` that the `\n`→`<br>` rich-HTML conversion (#202) assumes menus carry no `<pre>`/preformatted content. py_compile + pytest + ruff.
<!-- SECTION:NOTES:END -->

