"""Unit tests for the local voice-note STT helper.

- covers model-cache path, availability probing, API shape
- heavy ffmpeg and faster-whisper path is exercised out-of-band
"""
import asyncio
import inspect
import os
import subprocess
import tempfile

import pytest

from app.core import transcribe


def test_default_model_root_is_sibling_of_workdirs():
    # Model cache sits beside the workdirs base, not inside.
    assert (transcribe.default_model_root("/var/lib/claude-tg-bot/workdirs")
            == "/var/lib/claude-tg-bot/models")
    # A trailing slash is normalised before taking the parent.
    assert (transcribe.default_model_root("/var/lib/claude-tg-bot/workdirs/")
            == "/var/lib/claude-tg-bot/models")
    # A bare relative base has no parent: just 'models'.
    assert transcribe.default_model_root("workdirs") == "models"


def test_availability_probes_return_bools_and_compose():
    assert isinstance(transcribe.ffmpeg_available(), bool)
    assert isinstance(transcribe._faster_whisper_available(), bool)
    # `available()` is exactly the AND of the two probes.
    assert transcribe.available() == (
        transcribe.ffmpeg_available() and transcribe._faster_whisper_available()
    )


def test_transcribe_is_async():
    assert inspect.iscoroutinefunction(transcribe.transcribe)


def test_decode_to_wav_removes_both_temp_files_on_ffmpeg_failure(monkeypatch, tmp_path):
    """A failed or timed-out ffmpeg decode leaves no temp file.

    - neither the source .oga nor the partial .wav
    - a RAM-backed /tmp makes a leak costly
    - regresses if `_decode_to_wav` stops cleaning `dst` on exception
    """
    seen = {}
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix=""):
        fd, path = real_mkstemp(suffix=suffix, dir=tmp_path)
        seen["src"] = path
        return fd, path

    def fake_run(argv, **kwargs):
        with open(argv[-1], "wb") as fh:        # ffmpeg writes a partial WAV
            fh.write(b"RIFFpartial")
        raise subprocess.CalledProcessError(1, argv, stderr=b"boom")   # then fails

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        transcribe._decode_to_wav(b"opus-bytes")

    src = seen["src"]
    dst = src[:-4] + "_16k.wav"
    assert not os.path.exists(src), "source .oga leaked on failure"
    assert not os.path.exists(dst), "partial .wav leaked on failure"


def test_decode_to_wav_returns_wav_and_removes_source_on_success(monkeypatch, tmp_path):
    """On success the decoded WAV is returned.

    - the caller unlinks it
    - source .oga is cleaned in the finally
    """
    seen = {}
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix=""):
        fd, path = real_mkstemp(suffix=suffix, dir=tmp_path)
        seen["src"] = path
        return fd, path

    def fake_run(argv, **kwargs):
        with open(argv[-1], "wb") as fh:
            fh.write(b"RIFFwav")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(subprocess, "run", fake_run)

    wav = transcribe._decode_to_wav(b"opus-bytes")
    try:
        assert os.path.exists(wav)                     # dst returned to the caller
        assert not os.path.exists(seen["src"])         # source .oga cleaned in finally
    finally:
        os.unlink(wav)


def test_decode_to_wav_cleans_source_when_write_fails(monkeypatch, tmp_path):
    """A failed source write still unlinks the source temp.

    - e.g. ENOSPC on a RAM-backed /tmp, before ffmpeg runs
    - the write must sit inside the try/finally
    """
    seen = {}
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix=""):
        fd, path = real_mkstemp(suffix=suffix, dir=tmp_path)
        seen["src"] = path
        return fd, path

    class _BoomFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, *a):
            raise OSError("ENOSPC")

    def fake_fdopen(fd, *a, **k):
        os.close(fd)                 # release mkstemp fd; the write fails
        return _BoomFile()

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(os, "fdopen", fake_fdopen)

    with pytest.raises(OSError):
        transcribe._decode_to_wav(b"opus-bytes")
    assert not os.path.exists(seen["src"]), "source .oga leaked on a write failure"


def test_decode_to_wav_cleans_up_on_ffmpeg_timeout(monkeypatch, tmp_path):
    """The 120s ffmpeg timeout also leaves no temp file.

    - same cleanup as CalledProcessError, distinct exception type
    """
    seen = {}
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix=""):
        fd, path = real_mkstemp(suffix=suffix, dir=tmp_path)
        seen["src"] = path
        return fd, path

    def fake_run(argv, **kwargs):
        with open(argv[-1], "wb") as fh:            # ffmpeg wrote a partial WAV
            fh.write(b"RIFFpartial")
        raise subprocess.TimeoutExpired(argv, 120)  # then the 120s kill fires

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        transcribe._decode_to_wav(b"opus-bytes")
    src = seen["src"]
    dst = src[:-4] + "_16k.wav"
    assert not os.path.exists(src) and not os.path.exists(dst), "temp files leaked on timeout"


def test_transcribe_rejects_oversized_decoded_audio(monkeypatch, tmp_path):
    """An oversized decoded WAV is rejected with `AudioTooLong`.

    - happens before the inference lock; WAV is unlinked
    - covers absent or understated Telegram duration metadata
    - a note can't hold `_infer_lock` or run inference
    """
    wav = tmp_path / "big_16k.wav"
    wav.write_bytes(b"\0" * (32000 * 5 + 65536 + 1))   # 1 byte over the 5s cap

    class _Model:
        def transcribe(self, *a, **k):
            raise AssertionError("inference must not run when the cap is exceeded")

    async def fake_get_model(*a, **k):
        return _Model()

    monkeypatch.setattr(transcribe, "_get_model", fake_get_model)
    monkeypatch.setattr(transcribe, "_decode_to_wav", lambda ogg: str(wav))

    with pytest.raises(transcribe.AudioTooLong):
        asyncio.run(transcribe.transcribe(b"x", download_root=str(tmp_path), max_seconds=5))
    assert not wav.exists()          # oversized WAV cleaned in finally
