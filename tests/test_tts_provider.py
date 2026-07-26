import pytest
from unittest.mock import Mock, AsyncMock

from alex_brain_client import CoreBrainClient, BrainClientError
from alex_tts import BrainTTSProvider, TTSError, TTSErrorCode

def test_brain_tts_provider_success():
    """Verify TTS provider correctly wraps successful synthesis."""
    import asyncio
    async def run():
        import base64
        # Smallest valid WAV with 1 PCM sample (16-bit, mono, 16kHz)
        wav_b64 = "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAA="
        wav_bytes = base64.b64decode(wav_b64)
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.return_value = {
            "audio_base64": wav_b64,
            "provider": "brain_tts",
            "metadata": {"test": "ok"}
        }

        provider = BrainTTSProvider(mock_client)
        result = await provider.synthesize("sess1", "req1", "Xin chào")

        assert result.session_id == "sess1"
        assert result.request_id == "req1"
        assert result.audio_data == wav_bytes
        assert result.provider == "brain_tts"
        
        mock_client.synthesize.assert_called_once_with("sess1", "req1", "Xin chào")
    asyncio.run(run())

def test_brain_tts_provider_empty_audio_raises_error():
    """Verify TTS provider raises error if Brain returns empty audio data."""
    import asyncio
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.return_value = {"audio_base64": ""}

        provider = BrainTTSProvider(mock_client)
        
        with pytest.raises(TTSError) as exc_info:
            await provider.synthesize("sess2", "req2", "Xin chào")

        assert exc_info.value.code == TTSErrorCode.INTERNAL_FAILURE
        assert "Empty audio" in str(exc_info.value)
    asyncio.run(run())

def test_brain_tts_provider_brain_error_raises_unavailable():
    """Verify TTS provider wraps BrainClientError as TTS_UNAVAILABLE."""
    import asyncio
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.side_effect = BrainClientError("brain_timeout")

        provider = BrainTTSProvider(mock_client)
        
        with pytest.raises(TTSError) as exc_info:
            await provider.synthesize("sess3", "req3", "Xin chào")

        assert exc_info.value.code == TTSErrorCode.SYNTHESIS_TIMEOUT
        assert "brain_timeout" in str(exc_info.value)
    asyncio.run(run())
