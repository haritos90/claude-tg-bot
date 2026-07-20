---
id: TASK-375
title: >-
  Harden the interleave commit: pure-attachment replies drop the keypad and
  never notify; add coverage
status: To Do
assignee: []
created_date: '2026-07-15 19:39'
labels: []
dependencies: []
priority: medium
ordinal: 13362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The #373/#374 interleave path (streamer._commit_rich_interleaved) has a gap when a reply carries only out-of-band blocks (map pin, <svg> diagram, or wide table) and no prose. Every prose bubble is skipped, so last_text_idx is -1 and no message carries the inline keypad (#247) or pings the user. The prior placeholder-note path put a note plus footer in a rich bubble that carried both.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A pure-attachment reply (only pin, diagram, or wide table, no prose) still delivers the inline keypad and pings when notify is set
- [ ] #2 The rich-to-HTML per-segment fallback logs the failure and cannot double-fault out of finish()
- [ ] #3 tests/test_streamer.py covers keypad placement on the last prose bubble, a reply ending on a trailing attachment, a pure-attachment reply (keypad plus notification), a forced SendRichMessage failure exercising the fallback, disable_notification assertions, and an empty or desynced queue
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
streamer.py:1402 -- the keypad (reply_markup) rides the bubble at last_text_idx; a pure-attachment reply (last_text_idx == -1) attaches it to nothing, so the shell keypad is silently dropped. _send_location / _send_svg_image / _send_wide_table_image all hardcode disable_notification=True, so such a reply never pings even as the final answer (notify=True).
streamer.py:1419-1428 -- the footer-alone branch omits reply_markup and hardcodes disable_notification=True, and only runs when a footer exists. Fix: pass reply_markup=reply_markup and set disable_notification from notify on that send; when reply_markup is set but last_text_idx == -1 with no footer, still emit a minimal carrier (or hang the keypad on the last attachment) so it is never lost.
streamer.py:1410-1418 -- the per-segment rich-to-HTML fallback swallows the send failure with no log (unlike _commit_rich_markdown near line 1340, which warns) and computes markup.md_to_html(md) eagerly inside the except; a render raise there escapes _commit_rich_interleaved and propagates out of finish() while the turn lock is held (a stuck-turn risk). Add the warning log and move md_to_html into the _safe lambda.
streamer.py:1387-1392 -- a token whose per-type FIFO queue is empty is dropped silently, and any queue items left after the loop are dropped with no trace. Harmless while tokens and lists come from the same extraction pass; add a debug log or a drained check to catch future divergence.
<!-- SECTION:NOTES:END -->
