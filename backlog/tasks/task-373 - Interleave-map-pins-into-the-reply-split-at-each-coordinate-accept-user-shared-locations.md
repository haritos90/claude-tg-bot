---
id: TASK-373
title: >-
  Interleave map pins into the reply (split at each coordinate); accept
  user-shared locations
status: Done
assignee: []
created_date: '2026-07-12 15:13'
updated_date: '2026-07-12 15:14'
labels: []
dependencies: []
ordinal: 11362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A model reply that drops several location pins rendered as a stack of identical 'Location — sent on the map below.' placeholder lines, with every pin batched (detached) at the very end of the message. Make the reply SPLIT at each pin's insertion point and send the native map message THERE. Add the symmetric inbound path: a location or venue the user shares from Telegram's attach menu is delivered to the model as a normal turn.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Pins interleave: reply is split at each location block and the pin (venue card when named, else plain pin) is sent at that spot, in document order
- [ ] #2 Consecutive pins send back-to-back with no empty text bubble; footer + keypad ride the last non-empty bubble; per-segment rich->HTML fallback so a pins reply is never lost
- [ ] #3 A user-shared location/venue is received by the agent as a turn (coordinates, plus title/address for a venue)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Streamer (app/telegram/streamer.py): new _commit_rich_with_pins() splits the rich body on markup.LOCATION_TOKEN and sends text/pin/text interleaved — empty segment (back-to-back tokens) sends no bubble; footer + reply_markup ride the last non-empty text bubble (footer alone when the reply is pure pins); each rich bubble falls back to classic HTML on send failure (mirrors _commit_mixed) so it always delivers (no False/fallback return). _commit() now branches: locations present -> interleave (svg/wide-table notes stay inline and their images batch after, unchanged); no locations -> original single rich bubble. Draft path unchanged (still shows the localized note while streaming). Inbound: on_location handler on F.location | F.venue routes a user-shared point to _submit() as a model turn via i18n location.model_note / location.venue_model_note (en+ru); venue prefers message.venue.location, plain share uses message.location; nothing echoed (the user's own pin already shows). agent_context.md guidance updated to describe the split behavior + inbound capability. Tests: test_commit_rich_with_pins_interleaves_and_drops_placeholder + test_commit_rich_with_pins_footer_alone_when_reply_is_pure_pins (suite 281 green, +2 vs baseline 279). ruff clean; service restarted (Run polling).
<!-- SECTION:NOTES:END -->
