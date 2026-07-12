---
id: TASK-370
title: >-
  Voice feature follow-ups: .oga temp leak on write failure, unbounded
  faster-whisper pin, cap/timeout test gaps
status: Done
assignee: []
created_date: '2026-07-12 10:17'
updated_date: '2026-07-12 10:37'
labels:
  - reliability
  - bug
dependencies: []
priority: medium
ordinal: 8362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-ups to the voice-note transcription feature and the temp-file hardening in task-366.

- Temp-file leak on the pre-decode write path (resource): _decode_to_wav (app/core/transcribe.py:97-99) creates the source .oga with tempfile.mkstemp and writes the bytes BEFORE the try/finally that unlinks it (the finally is at :113). Task-366 hardened the ffmpeg-failure path (:110), but if os.fdopen/fh.write raises first — e.g. ENOSPC on the RAM-backed /tmp, the exact condition task-366 is concerned with — the source .oga is orphaned. Fix: unlink the source on a write failure too (move mkstemp+write inside a try that _safe_unlink(src) on exception, or bind dst first and cover both temp files with one try/finally).

- Unbounded dependency pin (reproducibility): requirements-voice.txt:11 pins `faster-whisper>=1.0` with no upper bound, against the repo convention of exact pins (requirements.txt uses ==). A future faster-whisper 2.x, with a transitive CTranslate2/onnxruntime bump, could silently break the m.transcribe(...) call on a fresh install. Fix: bound the range, e.g. `faster-whisper>=1.0,<2`.

- Test coverage (defense-in-depth): tests/test_transcribe.py does not exercise the max_seconds byte-cap reject-and-cleanup path in transcribe(), nor the TimeoutExpired arm of _decode_to_wav. Add a test that forces an oversized decoded WAV and asserts ValueError is raised AND the WAV is unlinked before _infer_lock is acquired; simulate TimeoutExpired in the ffmpeg-failure test to cover that arm.

- Redundant access gate (perf): on_voice runs _access_block before the download/transcription (correct, from task-365), then hands off to _submit, which calls _access_block again with the same key — doubling the rate-window DB queries per voice turn. No correctness impact. Fix: give _submit a gated=True fast-path, or replicate on_text's post-gate tail instead of calling _submit.

- Pending-restore race (correctness, minor): on_voice restores a popped arg-capture action with an unconditional `pending[_pkey] = action` after the multi-second transcription await. If the user set a new pending action during that window, the restore clobbers it. Fix: restore with pending.setdefault(_pkey, action) so a newer capture wins.

- Byte-cap error message (cosmetic): when the byte-cap trips (missing/understated duration plus an overlong note), transcribe() raises ValueError, which on_voice maps to voice.transcribe_failed ("could not transcribe") rather than voice.too_long. Optionally distinguish the length case.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A write failure before ffmpeg decode leaves no .oga temp file behind.
- [ ] #2 faster-whisper has an upper version bound.
- [ ] #3 Tests cover the max_seconds cap and the ffmpeg-timeout cleanup path.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED (all items). (1) _decode_to_wav (app/core/transcribe.py) moves the source-.oga mkstemp+write INSIDE the try/finally, so a write failure (e.g. ENOSPC on the RAM-backed /tmp) no longer orphans the source; the ffmpeg-failure dst cleanup is unchanged. (2) requirements-voice.txt bounds the dependency to faster-whisper>=1.0,<2. (3) A new AudioTooLong(ValueError) is raised by the max_seconds byte cap; on_voice maps it to voice.too_long instead of the generic transcribe_failed. (4) _submit gained gated=True; on_voice (which already gates before download + transcription) passes it, avoiding the redundant second _access_block (halves the per-voice-turn rate-window queries). (5) on_voice restores a popped pending arg-capture with pending.setdefault (both the download-error and empty-transcript paths), so a newer capture set during the transcription await is not clobbered. (6) tests/test_transcribe.py adds three tests: source cleanup on a write failure, temp cleanup on ffmpeg TimeoutExpired, and AudioTooLong + WAV cleanup before the inference lock on an oversized decode. Full suite 279 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
