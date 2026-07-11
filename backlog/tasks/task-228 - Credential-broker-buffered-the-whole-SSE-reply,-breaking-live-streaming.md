---
id: TASK-228
title: "Credential broker buffered the whole SSE reply, breaking live streaming"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 228
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DM streaming works again through the credential broker — replies stream token-by-token instead of arriving whole.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #119b broker (`deploy/cred-broker.py`) relayed the upstream response in its forward loop with `resp.read(65536)` — a `BufferedReader`-backed read that blocks until 65536 bytes arrive or the upstream closes. Any SSE reply under 64 KB (the common case) was accumulated whole and emitted only at end-of-stream, so the jailed CLI received no incremental `text_delta` events and the bot rendered each answer as one finished message. This was the real root cause behind #225's symptom, surfaced once the broker was enabled in production (streaming was unaffected before, when the CLI reached the API directly). Fix: `resp.read1(65536)` — at most one underlying socket read per iteration, returning bytes as soon as they arrive, so SSE frames stream through the broker unbuffered; the old line is kept commented with the #228 tag. Verified live: replies stream token-by-token again through the broker; py_compile + clean restart (broker up, polling).
<!-- SECTION:NOTES:END -->

