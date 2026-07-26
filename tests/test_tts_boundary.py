import pytest
import asyncio

from alex_tts import DeterministicTTSProvider, TTSResult, TTSError, TTSErrorCode

def test_tts_provider_success():
    provider = DeterministicTTSProvider()
    provider.next_result = TTSResult(
        session_id="s1",
        request_id="r1",
        audio_data=b"audio",
        provider="deterministic"
    )
    
    result = asyncio.run(provider.synthesize("s1", "r1", "Hello"))
    
    assert result.session_id == "s1"
    assert result.request_id == "r1"
    assert result.audio_data == b"audio"

def test_tts_provider_unavailable():
    provider = DeterministicTTSProvider()
    provider.next_result = TTSError(TTSErrorCode.TTS_UNAVAILABLE, "Offline")
    
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))
        
    assert exc.value.code == TTSErrorCode.TTS_UNAVAILABLE

def test_tts_provider_timeout():
    provider = DeterministicTTSProvider()
    provider.next_result = TTSError(TTSErrorCode.SYNTHESIS_TIMEOUT, "Timeout")
    
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))
        
    assert exc.value.code == TTSErrorCode.SYNTHESIS_TIMEOUT

def test_tts_provider_empty_text():
    provider = DeterministicTTSProvider()
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", ""))
        
    assert exc.value.code == TTSErrorCode.INTERNAL_FAILURE
