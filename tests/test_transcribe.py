"""Unit tests for the local voice-note STT helper (#363).

These cover the pure/glue logic — model-cache path derivation, availability probing,
and the public API shape. The heavy path (ffmpeg decode + faster-whisper inference)
needs the optional deps and a ~150 MB model, so it is exercised out-of-band, not here.
"""
import inspect

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
