---
id: TASK-16
title: optional voice-note input (transcribe → route as text)
status: Done
assignee: []
created_date: '2026-07-04 00:00'
updated_date: '2026-07-11 20:04'
labels:
  - features
dependencies: []
ordinal: 16
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort L · deferred._

Telegram delivers a voice note as `.ogg`/Opus; the Claude Agent SDK takes text (and images), not audio, so speech-to-text is a SEPARATE backend the bot must run. Options weighed: (1) local `faster-whisper` — no external key, audio stays on the host, but adds CPU/RAM + a model download that competes with the ~500 MB `claude` clients on a small box; (2) an external STT API (e.g. Deepgram / Whisper) — accurate and light on local resources, but needs a non-Anthropic key (allowed — only `ANTHROPIC_API_KEY` is banned), per-minute cost, and ships user audio to a third party; (3) Telegram Premium auto-transcription is NOT exposed to bots. Recommended when revived: local `faster-whisper` behind a `VOICE_STT` flag, transcribe in `asyncio.to_thread`, show the recognized text, then route it as a normal text turn; TTS on the reply is a heavier optional follow-up. Deferred pending a decision on the STT backend.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Done - superseded by #363 (Local speech-to-text for Telegram voice notes), which implements exactly this outcome: a Telegram voice note is transcribed on-device (faster-whisper + ffmpeg, host-side, never entering a jail) and routed as a normal text turn. Implementation in task-363 (Done); handler + temp-file hardening follow-ups in task-365 and task-366.
<!-- SECTION:NOTES:END -->
