---
id: TASK-207
title: "Cyrillic sample literal in tests/test_markup.py broke the English-only rule"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 207
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cyrillic sample literal in tests/test_markup.py broke the English-only rule
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `ensure_text_bom` test used a Cyrillic string literal as its non-ASCII sample, violating golden rule 1 (English-only outside the i18n/commands/menu translation surfaces). Replaced with `"café"`; the helper keys off the filename, not the content, so the BOM assertions are unaffected. py_compile + pytest + ruff.
<!-- SECTION:NOTES:END -->

