import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
import os

os.environ["MQTT_PASSWORD"] = "test"
os.environ["ALEX_API_KEY"] = "test_key"
os.environ["MQTT_USERNAME"] = "test"
os.environ["ALEX_TAILSCALE_KEY"] = "tskey-test"
os.environ["CORE_BRAIN_API_KEY"] = "test"

from fastapi import WebSocket
from app import v1_voice_stream, ALEX_API_KEY

def test_voice_websocket_requires_auth():
    async def run():
        # 1. No auth -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {}
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_once_with(code=1008)

        # 2. Invalid auth -> 1008
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"key": "wrong_key"}
        await v1_voice_stream(ws, "s1", "r1")
        ws.close.assert_called_once_with(code=1008)

        # 3. Valid auth -> Should proceed and accept (called by bounded_audio_transport)
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"key": ALEX_API_KEY}
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        ws.receive.side_effect = [{"text": "DONE"}] # Immediately terminate

        await v1_voice_stream(ws, "s1", "r1")
        
        # Accept should have been called
        ws.accept.assert_called_once()
        
    asyncio.run(run())
