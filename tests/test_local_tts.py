import asyncio
import io
import math
import struct
import wave
from unittest.mock import MagicMock, patch
import pytest

from alex_local_tts import (
    LocalTTSProvider,
    NullPlaybackSink,
    normalize_tts_pronunciation,
)
from alex_tts import TTSError, TTSErrorCode


def create_test_wav_bytes(sample_rate: int = 22050, duration_sec: float = 0.2) -> bytes:
    """Generate a valid RIFF/WAVE PCM16 mono byte stream for testing."""
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            sample = int(math.sin(2 * math.pi * 440 * (i / sample_rate)) * 32767)
            frames.extend(struct.pack("<h", sample))
        wav_out.writeframes(bytes(frames))
    return buf.getvalue()


def test_pronunciation_normalization_boundary():
    """Verify word-boundary aware pronunciation normalization."""
    assert normalize_tts_pronunciation("ALEX", "A-lếch") == "A-lếch"
    assert normalize_tts_pronunciation("Alex", "A-lếch") == "A-lếch"
    assert normalize_tts_pronunciation("alex", "A-lếch") == "A-lếch"
    assert normalize_tts_pronunciation("Xin chào ALEX, tôi là ai?", "A-lếch") == "Xin chào A-lếch, tôi là ai?"
    
    # Substring in unrelated words MUST NOT be modified
    assert normalize_tts_pronunciation("alexander đại đế", "A-lếch") == "alexander đại đế"
    assert normalize_tts_pronunciation("alexa bật đèn", "A-lếch") == "alexa bật đèn"


def test_local_tts_python_backend_success(tmp_path):
    """Verify python backend invokes synthesize_wav with normalized text and returns real non-empty WAV."""
    model_path = str(tmp_path / "test.onnx")
    config_path = str(tmp_path / "test.onnx.json")
    with open(model_path, "w") as f:
        f.write("mock_model")
    with open(config_path, "w") as f:
        f.write("{}")

    valid_wav = create_test_wav_bytes(sample_rate=22050, duration_sec=0.2)
    raw_frames = valid_wav[44:]

    mock_voice = MagicMock()
    called_text = []
    def mock_synth_wav(text, wav_out):
        called_text.append(text)
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(22050)
        wav_out.writeframes(raw_frames)

    mock_voice.synthesize_wav = mock_synth_wav

    provider = LocalTTSProvider(model_path=model_path, config_path=config_path, backend="python")
    provider._piper_voice = mock_voice
    provider._voice_loaded = True

    display_text = "Xin chào ALEX"
    result = asyncio.run(provider.synthesize("s1", "r1", display_text))
    
    # 1. Display text is unmodified outside TTS
    assert display_text == "Xin chào ALEX"
    # 2. Pronunciation-normalized text was passed to Piper
    assert called_text == ["Xin chào A-lếch"]
    # 3. Audio binary assertions
    assert result.session_id == "s1"
    assert result.request_id == "r1"
    assert result.provider == "local_tts"
    assert len(result.audio_data) > 44
    assert result.metadata["sample_rate"] == 22050
    assert result.metadata["channels"] == 1
    assert result.metadata["duration_seconds"] > 0


def test_local_tts_python_backend_missing_synthesize_wav_fails(tmp_path):
    """Verify python backend fails truthfully if PiperVoice runtime lacks synthesize_wav method."""
    model_path = str(tmp_path / "test.onnx")
    config_path = str(tmp_path / "test.onnx.json")
    with open(model_path, "w") as f:
        f.write("mock")
    with open(config_path, "w") as f:
        f.write("{}")

    mock_voice = MagicMock(spec=["synthesize"])  # has synthesize, but NOT synthesize_wav

    provider = LocalTTSProvider(model_path=model_path, config_path=config_path, backend="python")
    provider._piper_voice = mock_voice
    provider._voice_loaded = True

    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))

    assert exc.value.code == TTSErrorCode.TTS_UNAVAILABLE
    assert "missing required synthesize_wav method" in str(exc.value)



def test_local_tts_missing_model_file(tmp_path):
    """Verify missing model or config raises TTSError(TTS_UNAVAILABLE)."""
    model_path = str(tmp_path / "non_existent.onnx")
    provider = LocalTTSProvider(model_path=model_path, backend="python")

    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))

    assert exc.value.code == TTSErrorCode.TTS_UNAVAILABLE


def test_local_tts_strict_backend_rejection(tmp_path):
    """Verify unknown backend or missing python library rejects without silent fallback."""
    model_path = str(tmp_path / "test.onnx")
    config_path = str(tmp_path / "test.onnx.json")
    with open(model_path, "w") as f:
        f.write("mock")
    with open(config_path, "w") as f:
        f.write("{}")

    provider = LocalTTSProvider(model_path=model_path, config_path=config_path, backend="invalid_backend")
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))

    assert exc.value.code == TTSErrorCode.TTS_UNAVAILABLE


def test_local_tts_empty_and_oversized_text():
    """Verify empty text and text > 4096 chars are rejected."""
    provider = LocalTTSProvider()

    with pytest.raises(TTSError) as exc1:
        asyncio.run(provider.synthesize("s1", "r1", ""))
    assert exc1.value.code == TTSErrorCode.INTERNAL_FAILURE

    oversized = "a" * 4097
    with pytest.raises(TTSError) as exc2:
        asyncio.run(provider.synthesize("s1", "r1", oversized))
    assert exc2.value.code == TTSErrorCode.INTERNAL_FAILURE


def test_null_playback_sink():
    sink = NullPlaybackSink()
    asyncio.run(sink.play(b"audio"))
    assert sink.played_audio == b"audio"

    sink.cancel()
    asyncio.run(sink.play(b"more_audio"))
    assert sink.played_audio == b"audio"

