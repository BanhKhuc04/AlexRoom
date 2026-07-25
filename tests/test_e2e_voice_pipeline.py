import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from fastapi import WebSocket

from alex_stt import STTResult
from alex_tts import TTSResult
from alex_voice import VoiceSessionState, VoiceErrorCode
from alex_voice_transport import BoundedAudioTransport
from alex_wake_word import DeterministicWakeWordProvider, WakeWordState

def test_e2e_voice_pipeline():
    async def run():
        # 1. Wake word detects trigger
        wake_word = DeterministicWakeWordProvider()
        listen_task = asyncio.create_task(wake_word.listen())
        wake_word.simulate_wake_word()
        assert await listen_task == WakeWordState.DETECTED
        
        # 2. STT Provider
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="session_1", request_id="req_1", transcript="Bật đèn", is_final=True, provider="mock_stt"
        )
        
        # 3. Router
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "fast_action"
        router_response.tool_results = []
        router_response.assistant_text = "Đã bật đèn."
        router_dispatch.return_value = router_response
        
        # 4. TTS Provider
        tts_provider = AsyncMock()
        tts_provider.synthesize.return_value = TTSResult(
            session_id="session_1", request_id="req_1", audio_data=b"tts_audio_data_padding_" * 5, provider="mock_tts"
        )
        
        # 5. Playback Sink
        playback_sink = AsyncMock()
        
        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        
        # Client connects
        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"fake_audio_chunk_1"},
            {"bytes": b"fake_audio_chunk_2"},
            {"text": "DONE"}
        ]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state
        
        await transport.handle_websocket(ws, "session_1", "req_1")
        
        # Verify STT transcribed all combined audio chunks
        stt_provider.transcribe.assert_called_once_with("session_1", "req_1", b"fake_audio_chunk_1fake_audio_chunk_2")
        
        # Verify Router was called
        router_dispatch.assert_called_once()
        
        # Verify TTS was synthesized
        tts_provider.synthesize.assert_called_once_with("session_1", "req_1", "Đã bật đèn.")
        
        # Verify Audio was played back
        playback_sink.play.assert_called_once_with(b"tts_audio_data_padding_" * 5)
        
        # Verify websocket client received final completed status
        ws.send_json.assert_any_call({
            "type": "completed",
            "state": VoiceSessionState.COMPLETED.value,
            "session_id": "session_1",
            "request_id": "req_1",
            "transcript": "Bật đèn",
            "assistant_text": "Đã bật đèn.",
            "error_code": None
        })
        
    asyncio.run(run())
