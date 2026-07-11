---
id: TASK-225
title: "Streaming: DM replies arrived whole instead of token-by-token"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 225
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fixed via #228 — live token-by-token streaming restored through the credential broker. The earlier "Telegram stopped rendering drafts" conclusion was incorrect; the cause was a buffering bug in the credential broker.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
MISDIAGNOSED first as an external Telegram-side draft-rendering outage with "no code change" — that conclusion was WRONG. Real cause found in #228: the #119b credential broker (`deploy/cred-broker.py`), newly enabled on this deployment, relayed the upstream response in its forward loop with `resp.read(65536)`, a `BufferedReader`-backed read that BLOCKS until 64 KB accumulate or the upstream closes. A short SSE reply (< 64 KB — the common case) was therefore buffered whole and flushed only at end-of-stream, starving the jailed CLI of incremental `text_delta` events, so the bot rendered each answer as one finished message. Drafts (`sendRichMessageDraft`, Bot API 10.1) animate correctly — the break was UPSTREAM of the draft call, which is why the symptom appeared the day the broker went live and on every server running that code. Fixed in #228 (`resp.read1(65536)` — at most one socket read per iteration, streaming frames as they arrive). The bot still streams via drafts by design (never the ~1/sec `editMessageText` write-head).
<!-- SECTION:NOTES:END -->

