---
id: TASK-363
title: Local speech-to-text for Telegram voice notes
status: Done
assignee: []
created_date: '2026-07-11 09:50'
updated_date: '2026-07-11 14:22'
labels:
  - engine
dependencies: []
ordinal: 1362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A Telegram voice message is transcribed to text on-device and handled exactly like a typed turn. Fully local: the audio is decoded and transcribed in the host process, never entering the per-session sandbox and never leaving the server, with no third-party speech service and no API key. Recognition need not be perfect — the downstream agent reads through recognition errors the way it reads through typos. Off by default (optional deps).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New app/core/transcribe.py: ffmpeg decodes Opus/OGG to 16 kHz mono; faster-whisper (CTranslate2, CPU int8, default model "base") transcribes with beam_size=1 + VAD filtering + condition_on_previous_text=False (tuned for short notes on a 2-vCPU CPU box). Lazy singleton model reused across turns; inference serialized by an asyncio.Lock (one at a time) and all blocking work (ffmpeg, model load, inference) pushed off the event loop via asyncio.to_thread (CTranslate2 releases the GIL). available() gates the feature on ffmpeg-on-PATH + faster-whisper importable, so a checkout without the optional deps degrades gracefully instead of crashing.

Handler on_voice (F.voice) in app/telegram/handlers.py reuses _download (<=20 MB, the Bot API getFile cap) and _submit (injects the recognized text as a normal turn); a "Transcribing..." placeholder is edited into the recognized text so a mis-recognition is visible; duration gated by VOICE_MAX_SECONDS (default 300; 0 = off). Config (app/config.py): VOICE_TRANSCRIPTION (default off), VOICE_MODEL (tiny/base/small or a local path), VOICE_LANG (empty = autodetect; e.g. ru forces a language), VOICE_MAX_SECONDS, VOICE_MODEL_PATH (default: a models/ dir beside BASE_WORKDIR). i18n: 5 en/ru voice.* strings.

Optional deps kept OUT of the base install: ffmpeg (system binary) + faster-whisper (requirements-voice.txt). Docs: README (Features bullet + Optional-deps entry), new docs/voice.md, requirements.txt pointer. Tests: tests/test_transcribe.py (model-root derivation, availability composition, async API shape).

CPU-only (no GPU on this box): measured English near-perfect at ~0.4x realtime warm on base; Russian quality is validated by a real human voice note (synthetic espeak-ng TTS is not representative and transcribes poorly). Only F.voice is handled for now; audio files and video notes are easy follow-ons. Verified: compile + import + ruff + suite 272 green; live restart polling with VOICE_TRANSCRIPTION=1.

Follow-up (same batch): the text sent to the MODEL is prefixed with an i18n marker (voice.model_note, en+ru) stating it is an auto-transcribed voice note that may contain errors, so the agent knows the medium and reads for intent instead of guessing "looks like speech recognition"; the on-screen transcript bubble stays the clean recognized text. Validated end-to-end on a real Russian voice note.
<!-- SECTION:NOTES:END -->
