import pytest
import asyncio
from unittest.mock import Mock

from alex_stt import DeterministicSTTProvider, STTResult, STTError, STTErrorCode
from alex_voice import (
    VoiceSessionLifecycle,
    VoiceSessionState,
    VoiceInput,
    VoiceResponse,
    VoiceErrorCode,
    process_voice_transcript
)

def test_stt_provider_success():
    provider = DeterministicSTTProvider()
    provider.next_result = STTResult(
        session_id="s1",
        request_id="r1",
        transcript="Bật đèn",
        is_final=True,
        provider="deterministic"
    )
    
    result = asyncio.run(provider.transcribe("s1", "r1", b"audio"))
    
    assert result.session_id == "s1"
    assert result.request_id == "r1"
    assert result.transcript == "Bật đèn"
    assert result.is_final is True

def test_stt_provider_unavailable():
    provider = DeterministicSTTProvider()
    provider.next_result = STTError(STTErrorCode.STT_UNAVAILABLE, "Offline")
    
    with pytest.raises(STTError) as exc:
        asyncio.run(provider.transcribe("s1", "r1", b"audio"))
        
    assert exc.value.code == STTErrorCode.STT_UNAVAILABLE

def test_stt_provider_timeout():
    provider = DeterministicSTTProvider()
    provider.next_result = STTError(STTErrorCode.TRANSCRIPTION_TIMEOUT, "Timeout")
    
    with pytest.raises(STTError) as exc:
        asyncio.run(provider.transcribe("s1", "r1", b"audio"))
        
    assert exc.value.code == STTErrorCode.TRANSCRIPTION_TIMEOUT

def test_integration_partial_transcript_no_action():
    provider = DeterministicSTTProvider()
    provider.next_result = STTResult(
        session_id="s1",
        request_id="r1",
        transcript="Bật đ",
        is_final=False,
        provider="deterministic"
    )
    
    result = asyncio.run(provider.transcribe("s1", "r1", b"audio"))
    
    session = VoiceSessionLifecycle(result.session_id)
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = VoiceInput(
        session_id=result.session_id,
        request_id=result.request_id,
        transcript=result.transcript,
        is_final=result.is_final,
        source=result.provider,
        created_at="now"
    )
    
    router = Mock()
    resp = process_voice_transcript(session, voice_input, router)
    
    assert resp.state == VoiceSessionState.TRANSCRIBING
    router.dispatch.assert_not_called()

def test_integration_cancellation_before_stt_result():
    provider = DeterministicSTTProvider()
    provider.next_result = STTResult(
        session_id="s1",
        request_id="r1",
        transcript="Bật đèn",
        is_final=True,
        provider="deterministic"
    )
    
    session = VoiceSessionLifecycle("s1")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    # User cancels while transcribing
    session.cancel()
    
    # STT returns late result
    result = asyncio.run(provider.transcribe("s1", "r1", b"audio"))
    
    voice_input = VoiceInput(
        session_id=result.session_id,
        request_id=result.request_id,
        transcript=result.transcript,
        is_final=result.is_final,
        source=result.provider,
        created_at="now"
    )
    
    router = Mock()
    resp = process_voice_transcript(session, voice_input, router)
    
    # The late STT result should not resurrect the session, process_voice_transcript will raise VoiceSessionError and return CANCELLED
    assert resp.state == VoiceSessionState.CANCELLED
    assert resp.error_code == VoiceErrorCode.CANCELLED.value
    router.dispatch.assert_not_called()
