---
id: TASK-206
title: "Agent-created `.md`/`.txt` files delivered via outbox shipped without a UTF-8 BOM (mobile mojibake)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 206
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Markdown/text files the bot sends now open with correct characters on phones, in any language — no more garbled Cyrillic.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The long-reply document path already BOMs via `markup.as_document`, but the outbox channel (#187) shipped the agent's file bytes verbatim, so a `.md`/`.txt` containing non-ASCII (Cyrillic, accents, CJK) rendered as mojibake on viewers that guess the charset. New `markup.ensure_text_bom(bytes, name)` prepends a UTF-8 BOM to `.md`/`.txt` (idempotent; no-op for other types); applied on outbox delivery in `sessions._deliver_outbox`. Done bot-side so it is automatic for every session and language — no per-session agent effort. +6 tests. Deployed.
<!-- SECTION:NOTES:END -->

