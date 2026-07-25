import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from alex_stt import STTResult
from alex_voice import VoiceSessionState, VoiceErrorCode
from alex_voice_transport import BoundedAudioTransport

def test_bounded_audio_transport_success():
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="test", is_final=True, provider="test"
        )
        
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "fast_response"
        router_response.tool_results = []
        router_response.assistant_text = "OK"
        router_dispatch.return_value = router_response
        
        transport = BoundedAudioTransport(stt_provider, router_dispatch)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"audio_data"},
            {"text": "DONE"}
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        ws.accept.assert_called_once()
        stt_provider.transcribe.assert_called_once_with("s1", "r1", b"audio_data")
        router_dispatch.assert_called_once()
        
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": VoiceSessionState.COMPLETED.value,
            "session_id": "s1",
            "request_id": "r1",
            "transcript": "test",
            "assistant_text": "OK",
            "error_code": None
        })
        ws.close.assert_called_once()
    asyncio.run(run())


def test_bounded_audio_transport_cancel():
    async def run():
        stt_provider = AsyncMock()
        router_dispatch = Mock()
        transport = BoundedAudioTransport(stt_provider, router_dispatch)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"audio_data"},
            {"text": "CANCEL"}
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        ws.accept.assert_called_once()
        stt_provider.transcribe.assert_not_called()
        router_dispatch.assert_not_called()
        
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": "CANCELLED",
            "session_id": "s1",
            "request_id": "r1",
            "reason": "cancelled"
        })
        ws.close.assert_called_once()
    asyncio.run(run())


def test_bounded_audio_transport_disconnect():
    async def run():
        stt_provider = AsyncMock()
        router_dispatch = Mock()
        transport = BoundedAudioTransport(stt_provider, router_dispatch)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = WebSocketDisconnect()
        ws_state = Mock()
        ws_state.name = "DISCONNECTED"
        ws.client_state = ws_state
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        stt_provider.transcribe.assert_not_called()
        router_dispatch.assert_not_called()
        ws.send_json.assert_not_called()
        ws.accept.assert_called_once()
    asyncio.run(run())


def test_bounded_audio_transport_max_chunk_size():
    async def run():
        stt_provider = AsyncMock()
        router_dispatch = Mock()
        transport = BoundedAudioTransport(stt_provider, router_dispatch)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"x" * (1024 * 512 + 1)},
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state
        
        stt_provider.transcribe.side_effect = Exception("Empty")
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        ws.close.assert_called_once()
    asyncio.run(run())
