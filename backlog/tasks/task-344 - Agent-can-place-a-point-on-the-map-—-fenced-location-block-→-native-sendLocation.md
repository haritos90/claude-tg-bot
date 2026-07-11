---
id: TASK-344
title: "Agent can place a point on the map — fenced `location` block → native sendLocation/sendVenue"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 344
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ask the bot where a place is (e.g. "where is the Eiffel Tower?") and it replies with a real Telegram map pin — a named venue card when it knows the place's name and address.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Both chat AND code mode can now drop a real Telegram map pin: the agent emits a fenced `location` code block holding a JSON object and the streamer sends it as a native `sendLocation` pin (or a `sendVenue` card when the block names a place via `title`+`address`). Mirrors the SVG-as-photo side-channel (#295) and is purely additive — the `<svg>`→PNG path is untouched. New `markup.extract_locations` (+ `LOCATION_TOKEN`, `_coerce_location`) pulls each complete block out, validates lat∈[−90,90] / lon∈[−180,180] (accepts `lat`/`latitude`, `lon`/`lng`/`longitude`; `title`/`address` optional), and leaves a localized note where it was — a malformed / out-of-range / non-JSON block is left as text so nothing is silently dropped or sent as a bogus pin. `streamer` extracts locations alongside svgs / wide-tables in the final commit and sends each pin after the bubble (`_send_location` → `send_venue` when titled, else `send_location`); the draft path hides the raw JSON while it streams (`_location_notes` + `_hide_unclosed_location`), mirroring the svg hide. New i18n key `stream.location` (en + ru). The `agent_context.md` Rendering section documents the exact block the streamer recognizes so the agent emits it on "where is X" / "show it on a map" / coordinate requests. compile + import + ruff + suite 250 green (+focused `extract_locations` test: pin, venue, `geo` alias, numeric-string coords, two-block order, out-of-range→text, non-JSON→text); live restart "Run polling".
<!-- SECTION:NOTES:END -->

