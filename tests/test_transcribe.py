"""Unit tests for the local voice-note STT helper (#363).

These cover the pure/glue logic — model-cache path derivation, availability probing,
and the public API shape. The heavy path (ffmpeg decode + faster-whisper inference)
needs the optional deps and a ~150 MB model, so it is exercised out-of-band, not here.
"""
import inspect
import os
import subprocess
import tempfile

import pytest

from app.core import transcribe


def test_default_model_root_is_sibling_of_workdirs():
    # the model cache sits next to the workdirs base, not inside it
    assert (transcribe.default_model_root("/var/lib/claude-tg-bot/workdirs")
            == "/var/lib/claude-tg-bot/models")
    # a trailing slash is normalised away before taking the parent
    assert (transcribe.default_model_root("/var/lib/claude-tg-bot/workdirs/")
            == "/var/lib/claude-tg-bot/models")
    # a bare relative base has no parent → just "models"
    assert transcribe.default_model_root("workdirs") == "models"


def test_availability_probes_return_bools_and_compose():
    assert isinstance(transcribe.ffmpeg_available(), bool)
    assert isinstance(transcribe._faster_whisper_available(), bool)
    # available() is exactly the AND of the two probes
    assert transcribe.available() == (
        transcribe.ffmpeg_available() and transcribe._faster_whisper_available()
    )


def test_transcribe_is_async():
    assert inspect.iscoroutinefunction(transcribe.transcribe)


def test_decode_to_wav_removes_both_temp_files_on_ffmpeg_failure(monkeypatch, tmp_path):
    """#366: a failed/timed-out ffmpeg decode must leave NO temp file behind — neither the
    source .oga nor the partial .wav ffmpeg may already have written (a RAM-backed /tmp makes a
    leak costly). Regresses if _decode_to_wav stops cleaning `dst` on the exception path."""
    seen = {}
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix=""):
        fd, path = real_mkstemp(suffix=suffix, dir=tmp_path)
        seen["src"] = path
        return fd, path

    def fake_run(argv, **kwargs):
        with open(argv[-1], "wb") as fh:        # ffmpeg writes a partial WAV (argv[-1] == dst)…
            fh.write(b"RIFFpartial")
        raise subprocess.CalledProcessError(1, argv, stderr=b"boom")   # …then fails

    monkeypatch.setattr(tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        transcribe._decode_to_wav(b"opus-bytes")

    src = seen["src"]
    dst = src[:-4] + "_16k.wav"
    assert not os.path.exists(src), "source .oga leaked on failure"
    assert not os.path.exists(dst), "partial .wav leaked on failure"


def test_decode_to_wav_returns_wav_and_removes_source_on_success(monkeypatch, tmp_path):
    """#366: on success the decoded WAV is returned (the caller unlinks it) and the source .oga
    is already cleaned in the finally."""
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
        assert not os.path.exists(seen["src"])         # source .oga cleaned in the finally
    finally:
        os.unlink(wav)
