import pytest
import asyncio
from unittest.mock import patch

from alex_tts import TTSError, TTSErrorCode
from alex_local_tts import LocalTTSProvider, NullPlaybackSink

def test_local_tts_success():
    provider = LocalTTSProvider()
    
    # Run mock synthesis
    result = asyncio.run(provider.synthesize("s1", "r1", "Hello world"))
    
    assert result.session_id == "s1"
    assert result.request_id == "r1"
    assert b"Hello world" in result.audio_data
    assert result.provider == "local_tts"

def test_local_tts_empty_text():
    provider = LocalTTSProvider()
    
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", ""))
        
    assert exc.value.code == TTSErrorCode.INTERNAL_FAILURE


def test_null_playback_sink():
    sink = NullPlaybackSink()
    
    asyncio.run(sink.play(b"audio"))
    assert sink.played_audio == b"audio"
    
    # Cancel and play again
    sink.cancel()
    asyncio.run(sink.play(b"more_audio"))
    
    # Should not append because cancelled
    assert sink.played_audio == b"audio"

@patch("alex_local_tts._HAS_LOCAL_TTS", False)
def test_local_tts_unavailable():
    provider = LocalTTSProvider()
    
    with pytest.raises(TTSError) as exc:
        asyncio.run(provider.synthesize("s1", "r1", "Hello"))
        
    assert exc.value.code == TTSErrorCode.TTS_UNAVAILABLE
