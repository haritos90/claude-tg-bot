---
id: TASK-365
title: >-
  Harden the voice-note handler: gate before transcribe, honor pending
  arg-capture
status: Done
assignee: []
created_date: '2026-07-11 17:12'
updated_date: '2026-07-11 17:26'
labels:
  - reliability
  - bug
dependencies: []
priority: high
ordinal: 3362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The on_voice handler (app/telegram/handlers.py) does expensive work before the access gate and does not participate in the pending arg-capture state machine.

- Gate ordering (correctness / DoS): on_voice downloads the Telegram file (~5504) and runs faster-whisper transcription (~5519) BEFORE the per-user access gate, which only runs later inside _submit (~5551). A quota-exhausted or code-denied allowlisted user still triggers the full download + CPU transcription (serialized on the single global inference lock) and sees a transcript bubble followed by a denial. Fix: resolve the session key and call _access_block(uid, uname, lang, key) at the top of on_voice, after the flag/duration checks and before _download, returning the denial the same way on_text does (~5260).
- Pending arg-capture (correctness): unlike on_text (which pops pending first, ~5253), on_voice never consults pending. A voice note that arrives while a command awaits its free-text argument (/new, /allow, /rename, /secret, /schedule, session Search, rename:<key>) is routed to the model as a turn AND leaves the pending action stuck, so the user's next text is mis-consumed as the stale argument. Fix: mirror on_text — pop pending and dispatch through _run_pending with the transcript (or reject with the /cancel hint) before submitting.
- Forum-topic threading (minor; Topics is frozen): the Transcribing placeholder and transcript are posted via message.answer (~5515), which omits message_thread_id, so in a supergroup-topic session they land in General instead of the thread. DM is unaffected. Fix only if Topics is revived: route the placeholder through the reply() helper.
- Audio files (open decision): only F.voice is handled; F.audio (a native audio/music message) matches no handler and is dropped silently. Confirm this is intended for the voice-note scope, or add a handler / user-facing notice.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. on_voice (app/telegram/handlers.py) now: (1) pops any pending arg-capture action up front like on_text — a voice note that answers a command prompt (/rename, /allow, /secret, /schedule, session Search, rename:<key>) is dispatched via _run_pending with the transcript instead of a model turn, and the capture is restored if the download errors or transcription fails; (2) resolves the session key and runs _access_block BEFORE the download + CPU transcription for a real turn, so a quota-exhausted / code-denied user is rejected without burning the single inference lock (the resolved key is passed to _submit to avoid a second idle rotation). The transcribe placeholder now carries message_thread_id so it stays in the originating forum topic if group sessions are ever revived (None/ignored in a DM). F.audio (music/audio files) stays intentionally unhandled: the feature is scoped to voice notes and the size/duration guards are voice-note shaped. Full suite 275 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
