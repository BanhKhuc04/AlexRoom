import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from alex_stt import STTResult
from alex_tts import TTSResult
from alex_voice import VoiceSessionState
from alex_voice_transport import BoundedAudioTransport

def test_bare_in_orchestration_pipeline_success():
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="Bật đèn", is_final=True, provider="mock_stt"
        )
        
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "fast_action"
        router_response.tool_results = []
        router_response.assistant_text = "Đã bật đèn."
        router_dispatch.return_value = router_response
        
        tts_provider = AsyncMock()
        tts_provider.synthesize.return_value = TTSResult(
            session_id="s1", request_id="r1", audio_data=b"tts_audio_data_padding_" * 5, provider="mock_tts"
        )
        
        playback_sink = AsyncMock()
        
        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"audio_data"},
            {"text": "DONE"}
        ]
        ws.application_state = WebSocketState.CONNECTED
        ws.client_state = WebSocketState.CONNECTED
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        # Verify the entire pipeline was called
        stt_provider.transcribe.assert_called_once_with("s1", "r1", b"audio_data")
        router_dispatch.assert_called_once()
        tts_provider.synthesize.assert_called_once_with("s1", "r1", "Đã bật đèn.")
        playback_sink.play.assert_called_once_with(b"tts_audio_data_padding_" * 5)
        
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": VoiceSessionState.COMPLETED.value,
            "is_action": False,
            "session_id": "s1",
            "request_id": "r1",
            "transcript": "Bật đèn",
            "assistant_text": "Đã bật đèn.",
            "error_code": None
        })
        
    asyncio.run(run())

def test_bare_in_orchestration_pipeline_no_text():
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="test", is_final=True, provider="mock_stt"
        )
        
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "silent_action"
        router_response.assistant_text = ""
        router_dispatch.return_value = router_response
        
        tts_provider = AsyncMock()
        playback_sink = AsyncMock()
        
        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"audio_data"},
            {"text": "DONE"}
        ]
        ws.application_state = WebSocketState.CONNECTED
        ws.client_state = WebSocketState.CONNECTED
        
        await transport.handle_websocket(ws, "s1", "r1")
        
        tts_provider.synthesize.assert_not_called()
        playback_sink.play.assert_not_called()
        
    asyncio.run(run())
