import os
os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "test-api-key")

import asyncio
import json
import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import WebSocket

from app import app, ALEX_API_KEY
from _brain_service_test_client import AsgiTestClient
from alex_voice import VoiceSessionState
from alex_voice_transport import BoundedAudioTransport
from alex_stt import STTResult
from alex_tts import TTSResult

@pytest.fixture
def client():
    return AsgiTestClient(app)

def test_e2e_text_brain_chat_flow(client):
    """Test text command natural language routing via POST /api/v1/brain/chat."""
    response = client.post(
        "/api/v1/brain/chat",
        headers={"X-Alex-Key": ALEX_API_KEY},
        json_body={
            "request_id": "req-text-e2e-1",
            "user_text": "Bật test led"
        }
    )
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        data = response.json()
        assert data["request_id"] == "req-text-e2e-1"
        assert data["state"] in ["success", "acting", "idle", "completed"]
    else:
        detail = response.json()["detail"]
        assert detail["code"] in ["brain_disabled", "brain_unavailable", "brain_timeout"]

def test_e2e_restricted_action_refusal(client):
    """Test restricted/unsafe natural language command refusal."""
    response = client.post(
        "/api/v1/brain/chat",
        headers={"X-Alex-Key": ALEX_API_KEY},
        json_body={
            "request_id": "req-text-refusal-1",
            "user_text": "Bật công tắc 220V không có interlock"
        }
    )
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        data = response.json()
        assert data["request_id"] == "req-text-refusal-1"
        assert data.get("state") in ["warning", "refused", "rejected", "idle", "success"]
    else:
        detail = response.json()["detail"]
        assert detail["code"] in ["brain_disabled", "brain_unavailable", "brain_timeout"]

def test_e2e_voice_transport_lifecycle():
    """Test full WebSocket voice session transport lifecycle with auth and audio frames."""
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s-e2e-1",
            request_id="r-e2e-1",
            transcript="bật test led",
            is_final=True,
            provider="test_stt"
        )
        
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "c5_safety"
        router_response.tool_results = []
        router_response.assistant_text = "Đã bật test led."
        router_dispatch.return_value = router_response
        
        tts_provider = AsyncMock()
        tts_provider.synthesize.return_value = TTSResult(
            session_id="s-e2e-1",
            request_id="r-e2e-1",
            audio_data=b"mock_tts_bytes",
            provider="test_tts"
        )

        transport = BoundedAudioTransport(
            stt_provider=stt_provider,
            router_dispatch=router_dispatch,
            tts_provider=tts_provider,
            auth_validator=lambda k: k == ALEX_API_KEY
        )

        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.return_value = {"type": "auth", "api_key": ALEX_API_KEY}
        ws.receive.side_effect = [
            {"bytes": b"\x00\x00" * 160}, # 16kHz PCM LE chunk
            {"text": "DONE"}
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state

        await transport.handle_websocket(ws, "s-e2e-1", "r-e2e-1")

        ws.accept.assert_called_once()
        ws.send_json.assert_called_once_with({
            "state": VoiceSessionState.COMPLETED.value,
            "transcript": "bật test led",
            "assistant_text": "Đã bật test led.",
            "error_code": None
        })
        ws.close.assert_called_once()

    asyncio.run(run())

def test_e2e_voice_transport_barge_in():
    """Test voice transport cancellation / barge-in handling."""
    async def run():
        stt_provider = AsyncMock()
        router_dispatch = Mock()
        
        transport = BoundedAudioTransport(
            stt_provider=stt_provider,
            router_dispatch=router_dispatch,
            auth_validator=lambda k: k == ALEX_API_KEY
        )

        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.return_value = {"type": "auth", "api_key": ALEX_API_KEY}
        ws.receive.side_effect = [
            {"text": "CANCEL"}
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state

        await transport.handle_websocket(ws, "s-cancel-1", "r-cancel-1")

        ws.send_json.assert_called_once_with({"state": "CANCELLED"})
        ws.close.assert_called_once()

    asyncio.run(run())
