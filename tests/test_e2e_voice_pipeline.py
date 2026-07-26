import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from alex_stt import STTResult
from alex_tts import TTSResult
from alex_voice import VoiceSessionState, VoiceErrorCode
from alex_voice_transport import BoundedAudioTransport
from alex_wake_word import DeterministicWakeWordProvider, WakeWordState


def _ws_mock(*, connected: bool = True) -> AsyncMock:
    """Create a properly configured mock WebSocket for SafeWebSocketChannel."""
    ws = AsyncMock(spec=WebSocket)
    ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
    if connected:
        ws.application_state = WebSocketState.CONNECTED
        ws.client_state = WebSocketState.CONNECTED
    else:
        ws.application_state = WebSocketState.DISCONNECTED
        ws.client_state = WebSocketState.DISCONNECTED
    return ws


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
        ws = _ws_mock()
        ws.receive.side_effect = [
            {"bytes": b"fake_audio_chunk_1"},
            {"bytes": b"fake_audio_chunk_2"},
            {"text": "DONE"}
        ]

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
            "is_action": False,
            "session_id": "session_1",
            "request_id": "req_1",
            "transcript": "Bật đèn",
            "assistant_text": "Đã bật đèn.",
            "error_code": None
        })
        ws.close.assert_awaited_once_with(code=1000)

    asyncio.run(run())


def test_no_speech_bypasses_router_and_tts():
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="   ", is_final=True, provider="mock_stt"
        )
        router_dispatch = Mock()
        tts_provider = AsyncMock()
        playback_sink = AsyncMock()

        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        ws = _ws_mock()
        ws.receive.side_effect = [{"bytes": b"audio"}, {"text": "DONE"}]

        await transport.handle_websocket(ws, "s1", "r1")

        router_dispatch.assert_not_called()
        tts_provider.synthesize.assert_not_called()
        playback_sink.play.assert_not_called()

        emitted_types = [call[1][0].get("type") for call in ws.send_json.mock_calls]
        assert emitted_types == ["auth_ok", "transcribing", "no_speech"]
        ws.close.assert_awaited_once_with(code=1000)
    asyncio.run(run())


def test_empty_tts_audio_rejected_no_speaking_event():
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
            session_id="s1", request_id="r1", audio_data=b"x" * 44, provider="mock_tts"
        )
        playback_sink = AsyncMock()

        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        ws = _ws_mock()
        ws.receive.side_effect = [{"bytes": b"audio"}, {"text": "DONE"}]

        await transport.handle_websocket(ws, "s1", "r1")

        playback_sink.play.assert_not_called()

        for call in ws.send_json.mock_calls:
            assert call[1][0].get("type") != "speaking"
    asyncio.run(run())


def test_disconnect_releases_resources():
    async def run():
        stt_provider = AsyncMock()
        router_dispatch = Mock()
        tts_provider = AsyncMock()
        playback_sink = AsyncMock()

        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        ws = _ws_mock()
        ws.receive.side_effect = [{"text": '{"type": "cancel"}'}]

        await transport.handle_websocket(ws, "s1", "r1")

        stt_provider.transcribe.assert_not_called()
        router_dispatch.assert_not_called()
        tts_provider.synthesize.assert_not_called()

        ws.send_json.assert_any_call({
            "type": "completed",
            "state": "CANCELLED",
            "session_id": "s1",
            "request_id": "r1",
            "reason": "cancelled"
        })
        ws.close.assert_awaited_once_with(code=1000)
    asyncio.run(run())


def test_tool_only_structured_result_handled():
    async def run():
        from alex_brain_integration import CoreBrainChatResponse, CoreBrainToolResult

        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="Bật đèn", is_final=True, provider="mock_stt"
        )
        router_dispatch = Mock()
        router_response = CoreBrainChatResponse(
            request_id="r1",
            route="brain_inference",
            assistant_text="",
            proposed_tool_calls=[],
            tool_results=[CoreBrainToolResult(name="system_status", status="completed", result={})]
        )
        router_dispatch.return_value = router_response

        tts_provider = AsyncMock()
        playback_sink = AsyncMock()

        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        ws = _ws_mock()
        ws.receive.side_effect = [{"bytes": b"audio"}, {"text": "DONE"}]

        await transport.handle_websocket(ws, "s1", "r1")

        tts_provider.synthesize.assert_not_called()

        found = False
        for call in ws.send_json.mock_calls:
            msg = call[1][0]
            if msg.get("type") == "completed":
                assert msg.get("error_code") is None
                assert msg.get("assistant_text") == ""
                found = True
            assert msg.get("type") != "speaking"
            assert msg.get("type") != "error"
        assert found
    asyncio.run(run())


@pytest.mark.parametrize("error_code", [
    "brain_busy",
    "brain_timeout",
    "provider_error",
    "empty_generation",
    "invalid_generation"
])
def test_brain_error_codes_clean_exit(error_code):
    async def run():
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="s1", request_id="r1", transcript="Bật đèn", is_final=True, provider="mock_stt"
        )
        router_dispatch = Mock()
        from alex_brain_client import BrainClientError
        router_dispatch.side_effect = BrainClientError(error_code)

        tts_provider = AsyncMock()
        playback_sink = AsyncMock()

        transport = BoundedAudioTransport(stt_provider, router_dispatch, tts_provider, playback_sink)
        ws = _ws_mock()
        ws.receive.side_effect = [{"bytes": b"audio"}, {"text": "DONE"}]

        await transport.handle_websocket(ws, "s1", "r1")

        tts_provider.synthesize.assert_not_called()
        for call in ws.send_json.mock_calls:
            assert call[1][0].get("type") != "speaking"

        ws.close.assert_awaited_once_with(code=1000)

        ws.send_json.assert_any_call({
            "type": "error",
            "session_id": "s1",
            "request_id": "r1",
            "error_code": error_code,
            "detail": "Không có phản hồi từ hệ thống."
        })
    asyncio.run(run())
