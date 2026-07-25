import pytest
import asyncio
from unittest.mock import Mock, patch

from alex_stt import STTError, STTErrorCode
from alex_local_stt import FasterWhisperSTTProvider

def test_faster_whisper_unavailable_if_no_model():
    # If we pass a bogus model size or the library is missing, it should fail gracefully
    # rather than crashing the system.
    provider = FasterWhisperSTTProvider(model_size="invalid_size_that_doesnt_exist")
    
    with pytest.raises(STTError) as exc:
        asyncio.run(provider.transcribe("s1", "r1", b"audio_data"))
        
    assert exc.value.code == STTErrorCode.STT_UNAVAILABLE


@patch("alex_local_stt._HAS_WHISPER", True)
def test_faster_whisper_success_mocked():
    with patch("alex_local_stt.WhisperModel", create=True) as MockWhisperModel:
        mock_model = Mock()
        MockWhisperModel.return_value = mock_model

        mock_segment = Mock()
        mock_segment.text = " Bật đèn"
        mock_model.transcribe.return_value = ([mock_segment], None)

        provider = FasterWhisperSTTProvider()

        # Make sure the provider took the mocked model
        provider.model = mock_model

        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 100)
        valid_wav = buf.getvalue()

        result = asyncio.run(provider.transcribe("s1", "r1", valid_wav))

        assert result.session_id == "s1"
        assert result.request_id == "r1"
        assert result.transcript == "Bật đèn"
        assert result.is_final is True
        assert result.provider == "faster_whisper"
        assert result.metadata["model"] == "small"
        assert result.metadata["language"] == "vi"
        assert result.metadata["device"] == "cpu"
        assert result.metadata["compute_type"] == "int8"

        mock_model.transcribe.assert_called_once()
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs.get("language") == "vi"
        assert kwargs.get("condition_on_previous_text") is False


def test_faster_whisper_empty_audio():
    provider = FasterWhisperSTTProvider()
    provider.model = Mock()

    with patch("alex_local_stt._HAS_WHISPER", True):
        with pytest.raises(STTError) as exc:
            asyncio.run(provider.transcribe("s1", "r1", b""))

        assert exc.value.code == STTErrorCode.INTERNAL_FAILURE


def test_faster_whisper_env_configuration(monkeypatch):
    """Verify environment variables ALEX_STT_MODEL, ALEX_STT_LANGUAGE, etc. are honored."""
    monkeypatch.setenv("ALEX_STT_MODEL", "small")
    monkeypatch.setenv("ALEX_STT_LANGUAGE", "vi")
    monkeypatch.setenv("ALEX_STT_DEVICE", "cpu")
    monkeypatch.setenv("ALEX_STT_COMPUTE_TYPE", "int8")

    with patch("alex_local_stt._HAS_WHISPER", True), patch("alex_local_stt.WhisperModel", create=True) as MockWhisperModel:
        provider = FasterWhisperSTTProvider()
        assert provider.model_size == "small"
        assert provider.language == "vi"
        assert provider.device == "cpu"
        assert provider.compute_type == "int8"
        MockWhisperModel.assert_called_once_with("small", device="cpu", compute_type="int8")


def test_faster_whisper_no_silent_fallback_to_tiny():
    """Verify missing/failing configured model fails gracefully with STT_UNAVAILABLE without falling back to tiny."""
    with patch("alex_local_stt._HAS_WHISPER", True), patch("alex_local_stt.WhisperModel", create=True, side_effect=RuntimeError("Failed to load model weights")):
        provider = FasterWhisperSTTProvider(model_size="small")
        assert provider.model is None

        with pytest.raises(STTError) as exc:
            asyncio.run(provider.transcribe("s1", "r1", b"dummy_audio"))

        assert exc.value.code == STTErrorCode.STT_UNAVAILABLE
        assert "FasterWhisper model 'small' is not available" in str(exc.value)


