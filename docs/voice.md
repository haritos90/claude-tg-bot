# Voice-note transcription (local, on-device)

Send a Telegram voice message and the bot transcribes it to text locally, then
handles that text exactly as if you had typed it — the answer streams back the usual
way. The recognized text is shown first to make a mis-hearing visible at a glance.

Recognition doesn't need to be perfect: the downstream agent reads through
recognition errors the same way it reads through typos, hence no need for a complicated model.

## Dependencies

Two optional dependencies — both are necessary for voice input:

| Dependency | Install | Purpose |
|---|---|---|
| `ffmpeg` (system binary) | `apt install ffmpeg` | Decode Telegram Opus/OGG → 16 kHz mono PCM. |
| `faster-whisper` (pip) | `pip install -r requirements-voice.txt` | On-device speech-to-text (CTranslate2, CPU int8). |

If not installed: the bot detects the missing pieces and replies that
voice transcription is unavailable.

The speech model (~150 MB for `base`) downloads once on first use into a `models/`
directory beside `BASE_WORKDIR` (e.g. `/var/lib/.../models`), or `VOICE_MODEL_PATH` if set.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `VOICE_TRANSCRIPTION` | `0` (off) | `1` enables voice-note transcription. |
| `VOICE_MODEL` | `base` | faster-whisper size: `tiny` (fastest) / `base` / `small` (best), or a local model path. |
| `VOICE_LANG` | *(empty → autodetect)* | Force a language, e.g. `ru` or `en`, if autodetect misfires on short clips. |
| `VOICE_MAX_SECONDS` | `300` | Reject notes longer than this; `0` = no limit. |
| `VOICE_MODEL_PATH` | *(empty)* | Model cache dir; empty = a `models/` dir beside `BASE_WORKDIR`. |

## How it works

1. `on_voice` (`app/telegram/handlers.py`) receives the `F.voice` update and downloads the
   Opus/OGG bytes (≤ 20 MB, the Bot API cap; the real gate is `VOICE_MAX_SECONDS`).
2. `app/core/transcribe.py` decodes it with `ffmpeg` to 16 kHz mono and runs faster-whisper
   (`beam_size=1`, VAD filtering, no cross-window conditioning — tuned for short notes on a
   small CPU box).
3. Transcriptions are serialized and run off the event loop, so a
   transcription never blocks the poller or a live turn.
4. The recognized text replaces the "🎙 Transcribing…" placeholder and is submitted as a
   normal turn.

## Model choice & tuning

- `base` (default) balances quality and speed; English is near-perfect, Russian is good.
- Drop to `tiny` for lower latency on long notes if you can accept a rougher transcript
  (the agent still reads through it).
- Bump to `small` for the best accuracy when the box has spare CPU/RAM.
- If autodetection picks the wrong language on short clips, set `VOICE_LANG` parameter (e.g. `VOICE_LANG=en`).
