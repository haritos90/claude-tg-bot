---
id: TASK-367
title: >-
  Doc hygiene: first-person prose in voice.md; stale _DRAFT_KEEPALIVE symbol in
  troubleshooting.md
status: Done
assignee: []
created_date: '2026-07-11 17:12'
updated_date: '2026-07-11 17:26'
labels:
  - docs
dependencies: []
priority: medium
ordinal: 5362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two documentation-hygiene fixes in the current batch.

- docs/voice.md (~16): the "Why local" note uses first-person prose ("here we use faster-whisper"), which breaks the spec-voice rule (declarative, present-tense, no first-person) that this same batch tightens. Rewrite in third person (e.g. "faster-whisper is used") and drop the editorializing analogy.
- docs/troubleshooting.md (~24): references the draft keepalive constant as _DRAFT_KEEPALIVE; the actual symbol is _DRAFT_KEEPALIVE_SECS (app/telegram/streamer.py:98). Append _SECS so a reader's grep resolves to the real symbol.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. docs/voice.md "Why local" drops the first-person / editorializing sentence (the "here we use faster-whisper" line and the car-head-unit analogy) for a declarative "Recognition is performed on-device by faster-whisper (CTranslate2, CPU int8)." docs/troubleshooting.md corrects the keepalive constant reference _DRAFT_KEEPALIVE -> _DRAFT_KEEPALIVE_SECS (matches app/telegram/streamer.py:98).
<!-- SECTION:NOTES:END -->
