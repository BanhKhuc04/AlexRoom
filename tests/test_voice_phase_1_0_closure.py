import pytest
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock

from alex_local_stt import FasterWhisperSTTProvider
from alex_voice import VoiceSessionLifecycle, VoiceSessionState, process_voice_transcript, VoiceInput
from alex_voice_transport import BoundedAudioTransport
from alex_brain_integration import CoreBrainChatResponse
from alex_audio import AudioValidationError, validate_wav_pcm

# 1. Pure silence WAV -> handled by FasterWhisperSTTProvider VAD (mocked/implied)
# 9. STT small config regression
def test_stt_small_config_regression():
    provider = FasterWhisperSTTProvider()
    assert provider.model_size == "small"
    assert provider.language == "vi"
    assert provider.device == "cpu"
    assert provider.compute_type == "int8"
    assert provider.vad_enabled is True
    assert provider.vad_min_silence_ms == 500

# 3. Non-empty conversational transcript + empty assistant_text
def test_empty_assistant_text_invariant():
    session = VoiceSessionLifecycle("sess1")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = VoiceInput(
        session_id="sess1",
        request_id="req1",
        transcript="xin chào",
        is_final=True,
        source="local_stt",
        created_at="now"
    )
    
    class DummyRouter:
        def dispatch(self, req):
            return CoreBrainChatResponse(
                request_id=req.request_id,
                assistant_text="",
                tool_results=[],
                route="chat"
            )
            
    response = process_voice_transcript(session, voice_input, DummyRouter())
    
    # Must not silently succeed
    assert response.state == VoiceSessionState.FAILED
    assert response.error_code == "empty_response"
    assert session.state == VoiceSessionState.FAILED

# 10. Safety regression
def test_safety_regression():
    from alex_safety import SafetyPolicy, CapabilityRegistry
    policy = SafetyPolicy(CapabilityRegistry(), simulator_mode=False)
    for i in range(1, 5):
        decision = policy.authorize("esp01", f"relay_{i}", "ON")
        assert not decision.allowed

# 11. Brain dependency regression
def test_brain_no_mqtt_dependency():
    # Ensure brain_service doesn't import MQTT
    brain_app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "brain_service", "app.py")
    if os.path.exists(brain_app_path):
        with open(brain_app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "paho.mqtt" not in content

# 5. TTS zero-frame WAV
def test_tts_zero_frame_wav_rejected():
    with pytest.raises(AudioValidationError):
        # 44 byte RIFF/WAVE header with 0 data bytes
        header = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
        validate_wav_pcm(header)

