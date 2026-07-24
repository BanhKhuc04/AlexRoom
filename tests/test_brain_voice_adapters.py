import asyncio
import pytest
from unittest.mock import Mock, patch

from alex_brain_client import CoreBrainClient, CoreBrainConfig, BrainClientError
from alex_stt import BrainSTTProvider, STTError, STTErrorCode
from alex_tts import BrainTTSProvider, TTSError, TTSErrorCode

def test_brain_stt_provider_success():
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.transcribe.return_value = {
            "session_id": "s1",
            "request_id": "r1",
            "transcript": "Bật đèn phòng khách",
            "is_final": True,
            "provider": "brain_stt"
        }

        stt = BrainSTTProvider(mock_client)
        result = await stt.transcribe("s1", "r1", b"fake_pcm_data")

        assert result.session_id == "s1"
        assert result.request_id == "r1"
        assert result.transcript == "Bật đèn phòng khách"
        assert result.provider == "brain_stt"
        mock_client.transcribe.assert_called_once()

    asyncio.run(run())

def test_brain_stt_provider_unavailable():
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.transcribe.side_effect = BrainClientError("brain_unavailable")

        stt = BrainSTTProvider(mock_client)
        with pytest.raises(STTError) as exc_info:
            await stt.transcribe("s1", "r1", b"fake_pcm_data")
        
        assert exc_info.value.code == STTErrorCode.STT_UNAVAILABLE

    asyncio.run(run())

def test_brain_tts_provider_success():
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.return_value = {
            "session_id": "s1",
            "request_id": "r1",
            "audio_base64": "dHRzX2F1ZGlv", # base64 for "tts_audio"
            "provider": "brain_tts"
        }

        tts = BrainTTSProvider(mock_client)
        result = await tts.synthesize("s1", "r1", "Đã bật đèn.")

        assert result.session_id == "s1"
        assert result.request_id == "r1"
        assert result.audio_data == b"tts_audio"
        assert result.provider == "brain_tts"
        mock_client.synthesize.assert_called_once()

    asyncio.run(run())

def test_brain_tts_provider_unavailable():
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.side_effect = BrainClientError("brain_unavailable")

        tts = BrainTTSProvider(mock_client)
        with pytest.raises(TTSError) as exc_info:
            await tts.synthesize("s1", "r1", "Đã bật đèn.")
        
        assert exc_info.value.code == TTSErrorCode.TTS_UNAVAILABLE

    asyncio.run(run())
