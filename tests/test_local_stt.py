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
        
        # Mock the transcription result
        mock_segment = Mock()
        mock_segment.text = " Bật đèn"
        mock_model.transcribe.return_value = ([mock_segment], None)
        
        provider = FasterWhisperSTTProvider()
        
        # Make sure the provider took the mocked model
        provider.model = mock_model
        
        # Fake WAV data
        fake_wav = b"RIFF$" + b"\x00"*40
        
        result = asyncio.run(provider.transcribe("s1", "r1", fake_wav))
        
        assert result.session_id == "s1"
        assert result.request_id == "r1"
        assert result.transcript == "Bật đèn"
        assert result.is_final is True
        assert result.provider == "faster_whisper"
        mock_model.transcribe.assert_called_once()


def test_faster_whisper_empty_audio():
    provider = FasterWhisperSTTProvider()
    # Mocking that the model loaded successfully for this test
    provider.model = Mock()
    
    with patch("alex_local_stt._HAS_WHISPER", True):
        with pytest.raises(STTError) as exc:
            asyncio.run(provider.transcribe("s1", "r1", b""))
            
        assert exc.value.code == STTErrorCode.INTERNAL_FAILURE
