"""Local speech-to-text for Telegram voice messages (#363).

Fully on-device. A Telegram voice note (Opus in an OGG container) is decoded with
ffmpeg to 16 kHz mono PCM and transcribed by faster-whisper (CTranslate2, int8) in
the HOST bot process — the audio never enters the per-session jail and never leaves
the VPS. Recognition need not be perfect: the downstream agent tolerates recognition
errors the way it tolerates typos, so a small/fast model is sufficient.

ffmpeg + faster-whisper are OPTIONAL runtime deps. If either is missing this module
reports ``available() is False`` and the voice handler degrades gracefully, so a
checkout without them still imports and runs (the base requirements don't pull the
heavy CTranslate2 stack — see requirements-voice.txt).

Concurrency: the box is small (2 vCPUs), so ``_infer_lock`` serialises inference —
only one transcription runs at a time — and all blocking work (ffmpeg, model load,
inference) is pushed off the event loop with ``asyncio.to_thread`` (CTranslate2
releases the GIL during inference, so the poller stays responsive).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile

log = logging.getLogger("transcribe")

# Lazy singletons — the model is built on first use and reused across turns.
_model = None
_model_key: tuple[str, str] | None = None      # (name, compute_type) the live model was built with
_load_lock = asyncio.Lock()                    # guards (re)construction of the model
_infer_lock = asyncio.Lock()                   # serialises inference: one at a time on a 2-vCPU host


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    """True only if the whole pipeline can run (ffmpeg on PATH + faster-whisper importable)."""
    return ffmpeg_available() and _faster_whisper_available()


def default_model_root(base_workdir: str) -> str:
    """Model cache dir a level up from the workdirs base (e.g. /var/lib/claude-tg-bot/models).

    Keeps the ~150 MB model store out of any per-session workdir and off the repo tree.
    """
    return os.path.join(os.path.dirname(os.path.normpath(base_workdir)), "models")


async def _get_model(name: str, compute_type: str, download_root: str, cpu_threads: int):
    """Return the shared WhisperModel, building it (and downloading on first use) if needed."""
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

        _model = await asyncio.to_thread(_build)      # load/download blocks → off the loop
        _model_key = key
        log.info("faster-whisper loaded model=%s compute=%s root=%s", name, compute_type, download_root)
        return _model


def _safe_unlink(path: str) -> None:
    """Remove a temp file, ignoring a missing-file / permission error."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _decode_to_wav(ogg: bytes) -> str:
    """Opus/OGG bytes → path to a fresh 16 kHz mono wav temp file (caller unlinks it)."""
    fd, src = tempfile.mkstemp(suffix=".oga")
    with os.fdopen(fd, "wb") as fh:
        fh.write(ogg)
    dst = src[:-4] + "_16k.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav", dst],
            check=True, capture_output=True, timeout=120,
        )
    except Exception:
        # #366: on ffmpeg failure/timeout the caller never learns `dst` (it unlinks the wav
        # only on the SUCCESS path), so the partial file ffmpeg may already have written would
        # leak — costly on a RAM-backed /tmp. Remove it here before re-raising.
        _safe_unlink(dst)
        raise
    finally:
        _safe_unlink(src)                      # the source .oga is never needed past decode
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

    ``lang`` empty → autodetect; otherwise force that language (e.g. ``"ru"``). Returns the
    recognised text (possibly ``""`` for silence). Raises on hard failures (ffmpeg / model /
    decode) — the caller maps that to a user-facing "could not transcribe" reply.
    """
    m = await _get_model(model, compute_type, download_root, cpu_threads)
    wav = await asyncio.to_thread(_decode_to_wav, ogg)
    try:
        if max_seconds and max_seconds > 0:
            # #366: defense-in-depth cap on the ACTUAL decoded audio. The caller gates on the
            # Telegram-reported duration, but that metadata can be absent/understated; bounding
            # the decoded WAV keeps a long note from holding the single _infer_lock unboundedly.
            # 16 kHz mono s16le ≈ 32 kB/s; +64 kB slack covers the container header.
            try:
                actual = os.path.getsize(wav)
            except OSError:
                actual = 0
            if actual > 32000 * max_seconds + 65536:
                raise ValueError(f"decoded audio {actual} bytes exceeds the {max_seconds}s cap")
        async with _infer_lock:
            def _run():
                # beam_size=1 (greedy) + VAD (drop silence, curb hallucinated loops) +
                # no cross-window conditioning — tuned for short notes on a CPU box.
                segments, _info = m.transcribe(
                    wav, beam_size=1, language=(lang or None),
                    vad_filter=True, condition_on_previous_text=False,
                )
                return " ".join(s.text.strip() for s in segments).strip()

            return await asyncio.to_thread(_run)
    finally:
        _safe_unlink(wav)
