"""Local on-device speech-to-text for Telegram voice messages.

- ffmpeg decodes Opus/OGG to 16 kHz mono PCM
- faster-whisper transcribes in the host process
- Audio never enters the jail or leaves the VPS
- Both deps optional; `available()` is False if missing
- `_infer_lock` serialises inference; blocking work uses `asyncio.to_thread`
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile

log = logging.getLogger("transcribe")

# Lazy singletons; the model is built on first use.
_model = None
_model_key: tuple[str, str] | None = None      # (name, compute_type) of the live model
_load_lock = asyncio.Lock()                    # guards model (re)construction
_infer_lock = asyncio.Lock()                   # serialises inference on a 2-vCPU host


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    """True only if ffmpeg and faster-whisper are both usable."""
    return ffmpeg_available() and _faster_whisper_available()


def default_model_root(base_workdir: str) -> str:
    """Model cache dir, one level above the workdirs base.

    - Keeps the ~150 MB model out of workdirs
    """
    return os.path.join(os.path.dirname(os.path.normpath(base_workdir)), "models")


async def _get_model(name: str, compute_type: str, download_root: str, cpu_threads: int):
    """Return the shared WhisperModel, building it on first use.

    - First use may download the model
    """
    global _model, _model_key
    key = (name, compute_type)
    if _model is not None and _model_key == key:
        return _model
    async with _load_lock:
        if _model is not None and _model_key == key:  # re-check after awaiting the lock
            return _model
        from faster_whisper import WhisperModel

        os.makedirs(download_root, exist_ok=True)

        def _build():
            return WhisperModel(
                name, device="cpu", compute_type=compute_type,
                download_root=download_root, cpu_threads=cpu_threads,
            )

        _model = await asyncio.to_thread(_build)      # blocking load/download runs off-loop
        _model_key = key
        log.info("faster-whisper loaded model=%s compute=%s root=%s", name, compute_type, download_root)
        return _model


def _safe_unlink(path: str) -> None:
    """Remove a temp file, ignoring missing-file or permission errors."""
    try:
        os.unlink(path)
    except OSError:
        pass


class AudioTooLong(ValueError):
    """Decoded audio exceeds the caller's `max_seconds` byte cap.

    - Subclasses `ValueError`, so existing handlers still catch it
    - Distinct so the voice handler can show "too long"
    """


def _decode_to_wav(ogg: bytes) -> str:
    """Decode Opus/OGG bytes to a temp 16 kHz mono wav.

    - Caller unlinks the returned path
    """
    fd, src = tempfile.mkstemp(suffix=".oga")
    dst = src[:-4] + "_16k.wav"
    # Source write sits inside the try/finally.
    # - A write failure (ENOSPC) must not leak
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(ogg)
        subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav", dst],
            check=True, capture_output=True, timeout=120,
        )
    except Exception:
        # Remove the partial wav if ffmpeg fails or times out.
        # - Caller only unlinks the wav on success
        # - Matters because /tmp is RAM-backed
        # - Unlink is a no-op if the source write failed
        _safe_unlink(dst)
        raise
    finally:
        _safe_unlink(src)                      # source .oga not needed after decode
    return dst


async def transcribe(
    ogg: bytes,
    *,
    model: str = "base",
    lang: str = "",
    compute_type: str = "int8",
    download_root: str,
    cpu_threads: int = 2,
    max_seconds: int = 0,
) -> str:
    """Transcribe Opus/OGG voice bytes to text.

    - Empty `lang` autodetects; otherwise forces that language
    - Returns "" for silence
    - Raises on ffmpeg, model or decode failure
    """
    m = await _get_model(model, compute_type, download_root, cpu_threads)
    wav = await asyncio.to_thread(_decode_to_wav, ogg)
    try:
        if max_seconds and max_seconds > 0:
            # Cap the actual decoded audio size, as defense in depth.
            # - Telegram-reported duration can be absent or understated
            # - Bounds how long one note holds `_infer_lock`
            # - 16 kHz mono s16le is ~32 kB/s
            try:
                actual = os.path.getsize(wav)
            except OSError:
                actual = 0
            if actual > 32000 * max_seconds + 65536:
                # Raise `AudioTooLong`, a `ValueError`, so the reply says "too long".
                raise AudioTooLong(f"decoded audio {actual} bytes exceeds the {max_seconds}s cap")
        async with _infer_lock:
            def _run():
                # Greedy `beam_size=1`, VAD, no cross-window conditioning.
                # - Tuned for short notes on a CPU box
                # - VAD drops silence and curbs hallucinated loops
                segments, _info = m.transcribe(
                    wav, beam_size=1, language=(lang or None),
                    vad_filter=True, condition_on_previous_text=False,
                )
                return " ".join(s.text.strip() for s in segments).strip()

            return await asyncio.to_thread(_run)
    finally:
        _safe_unlink(wav)
