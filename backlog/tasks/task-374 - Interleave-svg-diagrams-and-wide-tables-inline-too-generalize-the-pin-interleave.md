---
id: TASK-374
title: >-
  Interleave <svg> diagrams and wide tables inline too (generalize the pin
  interleave)
status: Done
assignee: []
created_date: '2026-07-14 08:37'
updated_date: '2026-07-14 08:38'
labels: []
dependencies: []
ordinal: 12362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-up to the map-pin interleave: <svg> diagrams (rasterized to PNG) and wide (>20-col) tables (PNG) still rendered a placeholder note in the bubble with the image batched at the very END of the message, detached from the prose that introduces it. Generalize the interleave so EVERY out-of-band block — pin, diagram, wide table — is sent as its native message RIGHT WHERE its token sat, in document order. Enables multi-diagram walkthroughs (a diagram per step, each in place).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A reply's <svg> diagram and wide table are each sent as a PNG photo at their exact spot in the text, not batched at the end
- [ ] #2 Pins, diagrams, and tables mixed in one reply interleave together in document order; back-to-back blocks send with no empty bubble; footer+keypad ride the last prose bubble
- [ ] #3 Single unified path (no separate per-type send loops); the interleaver always delivers via per-segment rich->HTML fallback
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
markup.py: new split_on_attachment_tokens() + _ATTACH_TOKEN_RE — one regex over LOCATION_TOKEN | SVG_TOKEN | WIDE_TABLE_TOKEN, re.split KEEPS the tokens (even idx = prose, odd idx = a token sentinel). streamer.py: #373 _commit_rich_with_pins() generalized+renamed to _commit_rich_interleaved(rich_text, locations, svgs, wide_tables, footer, silent_first, reply_markup): walks the split parts, sends each prose run as a rich bubble and dispatches each token to _send_location / _send_svg_image / _send_wide_table_image from per-type FIFO queues (each extractor emits one token per item in document order, so queues drain in step). Empty prose run (leading/back-to-back tokens) -> no bubble; footer+keypad ride the last non-empty prose bubble (footer alone if the reply is pure attachments); per-segment rich->HTML fallback so nothing is lost; always delivers. _commit(): dropped the pre-branch _wide_table_notes/_svg_notes/_location_notes substitution (interleaver needs RAW tokens; those helpers still run on the DRAFT path); branch is now 'if locations or svgs or wide_tables -> interleave; else single rich bubble'. Draft path unchanged. Fallback (document/legacy) now only reached with all attachment lists empty -> its location-note/pin handling is an inert defensive no-op (comment updated). agent_context.md: <svg> guidance notes the image embeds at its spot (reply split around it) for inline multi-diagram walkthroughs. Tests: renamed the two #373 pin tests to the new method (added svgs/wide_tables args) + new test_commit_rich_interleaved_mixes_diagrams_tables_and_pins_in_order (monkeypatches the rasterizers, asserts rich/photo/photo/pin document order). Suite 282 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
