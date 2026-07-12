---
id: TASK-366
title: >-
  Voice transcription leaks the WAV temp file on ffmpeg failure; add internal
  size/time bound + cleanup test
status: Done
assignee: []
created_date: '2026-07-11 17:12'
updated_date: '2026-07-11 17:26'
labels:
  - reliability
  - bug
dependencies: []
priority: high
ordinal: 4362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
app/core/transcribe.py leaks the converted-WAV temp file when ffmpeg fails, and has no internal duration/size bound.

- Temp-file leak (resource): _decode_to_wav (~87-103) unlinks only the source file in its finally; the output WAV is cleaned solely by the caller's finally (~136), whose try begins AFTER the decode call (~122). So when _decode_to_wav raises (corrupt audio -> CalledProcessError, or the 120s TimeoutExpired kill), the output path is never bound in the caller and the partial WAV ffmpeg already wrote is never removed. Because /tmp is RAM-backed tmpfs on this host, repeated pathological/timeout notes accumulate partial WAVs in RAM until restart. Fix: in _decode_to_wav, unlink the output path on the exception path too (a single finally that removes both, or except -> safe_unlink(dst); raise).
- Missing internal bound (defense-in-depth): there is no wall-clock or size cap on the transcribe() call or on the decoded WAV inside the module; protection relies entirely on the caller's Telegram-duration check, which is skipped when the voice duration is absent/None. A large note with missing duration metadata can hold the single inference lock a long time, serializing all voice transcription. Fix: also gate on decoded-WAV byte size, and/or reject when duration metadata is absent.
- Test depth (coverage): tests/test_transcribe.py covers only default_model_root, the available() composition, and an iscoroutinefunction check; _decode_to_wav, the ffmpeg argv, and temp-file cleanup are untested, so the leak passes CI green. Fix: add a test that stubs ffmpeg and monkeypatches the model to assert BOTH temp files are unlinked on success and on a simulated ffmpeg failure. Keep to stubbed/real audio, not synthetic TTS.

Acceptance criteria:
- A failed or timed-out ffmpeg decode leaves no WAV or source temp file behind.
- A regression test asserts temp-file cleanup on both the success and the ffmpeg-failure paths.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. app/core/transcribe.py: (1) _decode_to_wav removes the output WAV on the ffmpeg exception path (except Exception -> _safe_unlink(dst); raise) in addition to the source .oga in finally, so a CalledProcessError or the 120s TimeoutExpired no longer orphans a partial WAV on the RAM-backed /tmp; a shared _safe_unlink helper replaces the inline try/except OSError blocks. (2) transcribe() gained a max_seconds parameter and caps the decoded WAV size (32 kB/s * max_seconds + 64 kB header slack) before acquiring _infer_lock, so a note whose Telegram duration metadata is absent or understated cannot hold the lock unboundedly; on_voice passes settings.voice_max_seconds. (3) tests/test_transcribe.py adds two tests asserting both temp files are removed on a simulated ffmpeg failure and that the WAV is returned + source cleaned on success. Full suite 275 green, ruff clean.
<!-- SECTION:NOTES:END -->
