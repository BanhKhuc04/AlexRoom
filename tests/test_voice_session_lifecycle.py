from datetime import datetime, timezone
import pytest
from unittest.mock import Mock, patch

from alex_voice import (
    VoiceSessionLifecycle,
    VoiceSessionState,
    VoiceInput,
    VoiceErrorCode,
    VoiceSessionError,
    process_voice_transcript,
)
from alex_brain_tools import BrainChatRequest
from alex_brain_integration import CoreBrainChatResponse
from alex_brain_client import BrainClientError

def _make_input(is_final: bool = True) -> VoiceInput:
    return VoiceInput(
        session_id="session-123",
        request_id="req-456",
        transcript="Test transcript",
        is_final=is_final,
        source="microphone",
        created_at=datetime.now(timezone.utc).isoformat()
    )


def test_initial_state():
    session = VoiceSessionLifecycle("session-123")
    assert session.state == VoiceSessionState.IDLE


def test_valid_chat_only_flow():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)
    session.transition_to(VoiceSessionState.COMPLETED)
    session.transition_to(VoiceSessionState.IDLE)
    assert session.state == VoiceSessionState.IDLE


def test_valid_action_flow():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.ACTING)
    session.transition_to(VoiceSessionState.SPEAKING)
    session.transition_to(VoiceSessionState.COMPLETED)
    assert session.state == VoiceSessionState.COMPLETED


def test_invalid_transition():
    session = VoiceSessionLifecycle("session-123")
    with pytest.raises(VoiceSessionError) as exc_info:
        session.transition_to(VoiceSessionState.SPEAKING)
    assert exc_info.value.code == VoiceErrorCode.INVALID_TRANSITION


def test_cancel_from_listening():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.cancel()
    assert session.state == VoiceSessionState.CANCELLED


def test_cancel_from_thinking():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.cancel()
    assert session.state == VoiceSessionState.CANCELLED


def test_cancel_from_speaking():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)
    session.cancel()
    assert session.state == VoiceSessionState.CANCELLED


def test_cancel_idempotency_and_completed_rejection():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)
    session.transition_to(VoiceSessionState.COMPLETED)
    session.cancel()
    # Should bounded no-op on completed
    assert session.state == VoiceSessionState.COMPLETED


def test_process_voice_partial_transcript():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    
    voice_input = _make_input(is_final=False)
    router = Mock()
    
    response = process_voice_transcript(session, voice_input, router)
    
    assert response.state == VoiceSessionState.LISTENING
    assert response.assistant_text is None
    router.dispatch.assert_not_called()


def test_process_voice_final_transcript_chat():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = _make_input(is_final=True)
    router = Mock()
    router.dispatch.return_value = CoreBrainChatResponse(
        request_id="req-456",
        assistant_text="I can help with that.",
        proposed_tool_calls=[],
        tool_results=[],
        route="fast_response",
        brain_called=False
    )
    
    response = process_voice_transcript(session, voice_input, router)
    
    assert response.state == VoiceSessionState.THINKING
    assert response.assistant_text == "I can help with that."
    assert response.session_id == "session-123"
    assert response.request_id == "req-456"
    assert response.metadata["route"] == "fast_response"
    
    # Verify it mapped transcript correctly
    router.dispatch.assert_called_once()
    called_request: BrainChatRequest = router.dispatch.call_args[0][0]
    assert called_request.request_id == "req-456"
    assert called_request.user_text == "Test transcript"


def test_process_voice_final_transcript_acting():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = _make_input(is_final=True)
    router = Mock()
    
    # We pretend the route returned was execute_action (mutations occurred)
    router.dispatch.return_value = CoreBrainChatResponse(
        request_id="req-456",
        assistant_text="Turned on the LED.",
        proposed_tool_calls=[],
        tool_results=[],
        route="deterministic_safe_action",
        brain_called=False
    )
    
    # We spy on transition_to to ensure it hits ACTING
    original_transition = session.transition_to
    transitions_seen = []
    def spied_transition(new_state):
        transitions_seen.append(new_state)
        original_transition(new_state)
        
    session.transition_to = spied_transition
    
    response = process_voice_transcript(session, voice_input, router)
    
    assert response.state == VoiceSessionState.ACTING
    assert VoiceSessionState.ACTING in transitions_seen


def test_process_voice_brain_timeout():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = _make_input(is_final=True)
    router = Mock()
    router.dispatch.side_effect = BrainClientError("brain_timeout")
    
    response = process_voice_transcript(session, voice_input, router)
    
    assert response.state == VoiceSessionState.FAILED
    assert response.error_code == VoiceErrorCode.BRAIN_TIMEOUT.value


def test_process_voice_cancellation_during_thinking():
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = _make_input(is_final=True)
    router = Mock()
    
    # Simulate a cancel that happens in another thread while dispatch is working
    def dispatch_side_effect(request):
        session.cancel()
        return CoreBrainChatResponse(
            request_id="req-456",
            assistant_text="Too late",
            route="fast_response"
        )
        
    router.dispatch.side_effect = dispatch_side_effect
    
    response = process_voice_transcript(session, voice_input, router)
    
    # The transition from THINKING to SPEAKING will fail (raising VoiceSessionError)
    # which is caught and correctly reports CANCELLED.
    assert response.state == VoiceSessionState.CANCELLED
    assert response.error_code == VoiceErrorCode.CANCELLED.value

def test_telemetry_invoked(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="alex.intelligence.telemetry")
    session = VoiceSessionLifecycle("session-123")
    session.transition_to(VoiceSessionState.LISTENING)
    
    assert any("voice_state_changed" in rec.message for rec in caplog.records)
