---
id: TASK-361
title: "Cyber-safeguard refusals were mislabeled as \"Invalid request to the model\""
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 361
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A model safety refusal (e.g. a cybersecurity-topic block) now shows a clear "the model declined this turn — try a new session or switch model" notice instead of the misleading "Invalid request to the model."
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A model REFUSAL arrives in-band as an `AssistantMessage` with `error == "invalid_request"` AND `stop_reason == "refusal"` — the refusal rides in the response *body*, so the HTTP call is 200 (the broker logs `/v1/messages -> 200`, there is no 400) and the engine never logged `invalid_request`, so the bot log was silent; the real reason (`stop_details.category == "cyber"`, plus a synthetic "flagged this message for a cybersecurity topic… apply for an exemption… try a new session or change your model" text) lived only in the CLI transcript. The engine mapped EVERY `invalid_request` to the generic "Invalid request to the model.", which reads like a client/malformed-request bug. Diagnosed from the transcript: a chat turn on a security topic tripped Opus 4.8's real-time cyber safeguard. Fix: `engine._refine_error()` detects the refusal (`stop_reason == "refusal"` + `invalid_request`) and — because the SDK's `AssistantMessage` exposes `error`+`stop_reason`+`content` but NOT `stop_details` — reads the cyber category off the explanation text (`_CYBER_REFUSAL_MARKERS`; a reworded safeguard falls back to the generic refusal, never to the old mislabel), yielding `err.cyber_refusal` (cyber) or `err.model_refusal` (other refusal), each localized en+ru, instead of `err.invalid_request`. A genuine malformed request (no `refusal` stop_reason) still maps to the unchanged `err.invalid_request`. `docs/troubleshooting.md` gains a runbook entry (200-not-400 trap, transcript grep, `/new`+`/model` recovery). compile + import + ruff + suite 269 green (3 focused tests: cyber → cyber_refusal, non-cyber refusal → model_refusal, real invalid_request → unchanged); live restart "Run polling".
<!-- SECTION:NOTES:END -->

