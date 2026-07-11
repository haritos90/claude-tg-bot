---
id: decision-9
title: "Whole reply as one rich message, streamed via Bot API 10.1 drafts"
date: '2026-07-04 00:00'
status: accepted
---
## Context

Splitting a reply into several messages, or snapping from plain to rich at the end, looked broken and inconsistent. Bot API 10.1 (post-cutoff) added rich blocks + draft streaming.

## Decision

Send the WHOLE reply as ONE rich `{"markdown"}` message, streamed token-by-token via `sendRichMessageDraft` and finalized with `sendRichMessage`. Tables stream row-by-row by clipping to a valid markdown prefix; drafts use the 32768-char limit; ATX headings are demoted to bold for one consistent body font.

## Consequences

- ChatGPT-style animation, one message, font consistency.
- Draft behaviour depends on brand-new Bot API — always verified against the LIVE docs, never memory.
- Supergroups can't get rich drafts (`TEXTDRAFT_PEER_INVALID`), so that surface stays deferred.

**Source tasks:** #164, #169, #172, #176, #237, #241, #353
