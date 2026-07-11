---
id: TASK-343
title: "Service unavailability surfaced only after a 2–5 min \"thinking\" hang during an outage"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 343
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During a service outage the bot now shows a clear "service is unavailable, please try again" message within about a minute, instead of leaving you watching "thinking…" for several minutes before any error appears.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
When the service is overloaded/erroring (5xx/529) the CLI retries the request internally with backoff and emits no message for minutes, but `engine.run()` iterated `receive_response()` with no timeout — so the user was left on an endless "thinking…" animation until the CLI finally surfaced `server_error`. Added a time-to-first-token watchdog in `engine.run()`: the wait for the FIRST streamed message is bounded by `MODEL_FIRST_TOKEN_TIMEOUT_SEC` (default 60s, 0 disables); on timeout the client is dropped and a localized `err.service_unavailable` is surfaced so the next message rebuilds cleanly. Only the first-token wait is bounded — once the model is streaming (`_progressed`) it is never interrupted, so a legitimate long tool call / build (no events for minutes) is unaffected; the old `async for` is kept commented with the #343 ref. New i18n key `err.service_unavailable` (en + ru). compile + import + ruff + suite 249 green + focused watchdog tests (stall→error+drop, content→no-false-positive, empty-stream, disabled=0); live restart "Run polling".
<!-- SECTION:NOTES:END -->

