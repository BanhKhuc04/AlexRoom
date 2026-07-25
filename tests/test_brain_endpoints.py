import base64
import pytest
from unittest.mock import patch, Mock

from _brain_service_test_client import AsgiTestClient
from brain_service.app import AUTH_HEADER, create_app
from brain_service.config import BrainServiceConfig

TEST_BRAIN_KEY = "test-brain-secret-key-12345"

@pytest.fixture
def brain_app():
    cfg = BrainServiceConfig(api_key=TEST_BRAIN_KEY)
    return create_app(cfg)

@pytest.fixture
def client(brain_app):
    return AsgiTestClient(brain_app)

def test_brain_stt_endpoint_auth_required(client):
    """Verify /v1/stt requires authentication header."""
    res = client.post("/v1/stt", json_body={"session_id": "s1", "request_id": "r1", "audio_base64": "dGVzdA=="})
    assert res.status_code == 401

def test_brain_stt_endpoint_success(client):
    """Verify /v1/stt returns transcription only and does not execute tools."""
    with patch("alex_local_stt.FasterWhisperSTTProvider.transcribe") as mock_transcribe:
        mock_transcribe.return_value = Mock(transcript="Bật đèn bàn", is_final=True, provider="faster_whisper")

        audio_b64 = base64.b64encode(b"\x00\x00" * 160).decode("utf-8")
        res = client.post(
            "/v1/stt",
            headers={AUTH_HEADER: TEST_BRAIN_KEY},
            json_body={
                "session_id": "s-stt-1",
                "request_id": "r-stt-1",
                "audio_base64": audio_b64,
                "language": "vi"
            }
        )

        assert res.status_code == 200
        data = res.json()
        assert data["session_id"] == "s-stt-1"
        assert data["request_id"] == "r-stt-1"
        assert data["transcript"] == "Bật đèn bàn"
        assert data["provider"] == "brain_stt"
        assert "tool_calls" not in data

def test_brain_tts_endpoint_auth_required(client):
    """Verify /v1/tts requires authentication header."""
    res = client.post("/v1/tts", json_body={"session_id": "s1", "request_id": "r1", "text": "Xin chào"})
    assert res.status_code == 401

def test_brain_tts_endpoint_success(client):
    """Verify /v1/tts returns audio only and cannot mutate Core state."""
    with patch("alex_local_tts.LocalTTSProvider.synthesize") as mock_synth:
        mock_synth.return_value = Mock(audio_data=b"audio_pcm_stream", provider="piper")

        res = client.post(
            "/v1/tts",
            headers={AUTH_HEADER: TEST_BRAIN_KEY},
            json_body={
                "session_id": "s-tts-1",
                "request_id": "r-tts-1",
                "text": "Đã bật đèn bàn."
            }
        )

        assert res.status_code == 200
        data = res.json()
        assert data["session_id"] == "s-tts-1"
        assert data["request_id"] == "r-tts-1"
        audio_bytes = base64.b64decode(data["audio_base64"])
        assert audio_bytes == b"audio_pcm_stream"
        assert data["provider"] == "brain_tts"
        assert "tool_calls" not in data
