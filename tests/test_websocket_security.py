import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
import os

os.environ["MQTT_PASSWORD"] = "test"
os.environ["ALEX_API_KEY"] = "test_key"
os.environ["MQTT_USERNAME"] = "test"
os.environ["ALEX_TAILSCALE_KEY"] = "tskey-test"
os.environ["CORE_BRAIN_API_KEY"] = "test"

from fastapi import WebSocket, WebSocketDisconnect
from app import v1_voice_stream, ALEX_API_KEY
from alex_voice_transport import BoundedAudioTransport

def test_voice_websocket_origin_validation():
    async def run():
        # 1. Missing origin -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000"}
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_with(code=1008)

        # 2. Hostile origin -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://evil.com"}
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_with(code=1008)

        # 3. Valid origin -> accept called
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = [{"type": "auth", "api_key": ALEX_API_KEY}]
        ws.receive.side_effect = [{"text": "DONE"}]
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        await v1_voice_stream(ws, "s1", "r1")
        ws.accept.assert_called_once()
    asyncio.run(run())

def test_voice_websocket_first_message_auth():
    async def run():
        # 1. Missing auth message (timeout or disconnect) -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = asyncio.TimeoutError()
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_with(code=1008)

        # 2. Invalid auth message -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = [{"type": "auth", "api_key": "wrong_key"}]
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_with(code=1008)

        # 3. Valid auth message -> Proceed
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = [{"type": "auth", "api_key": ALEX_API_KEY}]
        ws.receive.side_effect = [{"text": "DONE"}]
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        await v1_voice_stream(ws, "s1", "r1")
        # Should not close with 1008. It might close due to mock STT error.
        if ws.close.called:
            for call in ws.close.call_args_list:
                assert call.kwargs.get("code") != 1008
    asyncio.run(run())

def test_voice_websocket_session_byte_limit():
    async def run():
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = [{"type": "auth", "api_key": ALEX_API_KEY}]
        # Exceed session limit using multiple chunks
        ws.receive.side_effect = [
            {"bytes": b"a" * (1024 * 512)}, # 512KB
            {"bytes": b"a" * (1024 * 512)}, # 512KB
            {"bytes": b"a" * (1024 * 1024 * 5)}, # 5MB -> exceeds 5MB total
            {"text": "DONE"}
        ]
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        await v1_voice_stream(ws, "s1", "r1")
        
        # Should send CANCELLED due to exceeding limit
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": "CANCELLED",
            "session_id": "s1",
            "request_id": "r1",
            "reason": "cancelled"
        })
    asyncio.run(run())

def test_voice_websocket_chunk_byte_limit():
    async def run():
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive_json.side_effect = [{"type": "auth", "api_key": ALEX_API_KEY}]
        # Exceed chunk limit
        ws.receive.side_effect = [
            {"bytes": b"a" * (1024 * 512 + 1)}, # 512KB + 1
            {"text": "DONE"}
        ]
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        await v1_voice_stream(ws, "s1", "r1")
        
        # Should send CANCELLED due to exceeding limit
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": "CANCELLED",
            "session_id": "s1",
            "request_id": "r1",
            "reason": "cancelled"
        })
    asyncio.run(run())

