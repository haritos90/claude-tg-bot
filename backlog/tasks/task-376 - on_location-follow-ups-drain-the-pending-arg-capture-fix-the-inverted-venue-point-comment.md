---
id: TASK-376
title: >-
  on_location follow-ups: drain the pending arg-capture; fix the inverted
  venue-point comment
status: To Do
assignee: []
created_date: '2026-07-15 19:39'
labels: []
dependencies: []
priority: low
ordinal: 14362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two minor issues in the #373 inbound on_location handler (app/telegram/handlers.py) that delivers a Telegram location or venue to the model as a turn.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 on_location interacts predictably with a pending arg-capture, consistent with on_text and on_voice
- [ ] #2 The venue-point selection comment matches the code
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
handlers.py:5607-5637 -- on_location does not pop the pending arg-capture, unlike on_text and on_voice which pending.pop(_pkey(message)) first. If a command is mid-capture (for example /rename) and the user shares a location, the pin is submitted as a model turn while the pending prompt stays armed and silently consumes the next text message from the user. Either pop-and-ignore the pending, or refuse with a cancel-the-pending-prompt-first reply, for parity with the other content handlers.
handlers.py:5622-5625 -- the comment claims the code prefers the venue own point and falls back to the top-level location, but the code (message.location or (venue.location if venue is not None else None)) does the opposite: it prefers the top-level point. Functionally harmless because Telegram populates both with identical coordinates on a venue message. Reword the comment to say it prefers the top-level point and falls back to the venue location, or swap the operands to match the stated intent.
<!-- SECTION:NOTES:END -->
