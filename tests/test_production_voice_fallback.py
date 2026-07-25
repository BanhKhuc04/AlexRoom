import asyncio
import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import WebSocket

from alex_brain_client import CoreBrainClient, BrainClientError
from alex_stt import BrainSTTProvider, STTError, STTErrorCode
from alex_tts import BrainTTSProvider, TTSError, TTSErrorCode
from alex_voice_transport import BoundedAudioTransport
from alex_voice import VoiceSessionState

def test_brain_stt_unavailable_no_fake_transcript():
    """Verify STT unavailability raises STTError and does NOT produce fake transcript."""
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.transcribe.side_effect = BrainClientError("brain_unavailable")

        stt = BrainSTTProvider(mock_client)
        with pytest.raises(STTError) as exc_info:
            await stt.transcribe("s-prod-1", "r-prod-1", b"\x00\x00" * 160)

        assert exc_info.value.code == STTErrorCode.STT_UNAVAILABLE

        # Verify transport behavior on STT unavailability
        router_dispatch = Mock()
        transport = BoundedAudioTransport(stt_provider=stt, router_dispatch=router_dispatch)

        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [{"bytes": b"\x00\x00" * 160}, {"text": "DONE"}]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state

        await transport.handle_websocket(ws, "s-prod-1", "r-prod-1")

        # Router MUST NOT be called when STT fails
        router_dispatch.assert_not_called()
        # Error event MUST be emitted to UI
        ws.send_json.assert_any_call({
            "type": "error",
            "session_id": "s-prod-1",
            "request_id": "r-prod-1",
            "error_code": "stt_unavailable",
            "detail": "Brain STT error: brain_unavailable"
        })

    asyncio.run(run())

def test_brain_tts_unavailable_preserves_text_no_fake_audio():
    """Verify TTS unavailability preserves text result without fabricating fake speech audio."""
    async def run():
        mock_client = Mock(spec=CoreBrainClient)
        mock_client.synthesize.side_effect = BrainClientError("brain_unavailable")

        tts = BrainTTSProvider(mock_client)
        with pytest.raises(TTSError) as exc_info:
            await tts.synthesize("s-prod-2", "r-prod-2", "Đã bật đèn.")

        assert exc_info.value.code == TTSErrorCode.TTS_UNAVAILABLE

        # Verify transport behavior: text is preserved, error emitted, no fake audio
        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = Mock(
            session_id="s-prod-2",
            request_id="r-prod-2",
            transcript="bật đèn",
            is_final=True,
            provider="test"
        )
        
        router_dispatch = Mock()
        router_response = Mock()
        router_response.route = "c5_safety"
        router_response.tool_results = []
        router_response.assistant_text = "Đã bật đèn."
        router_dispatch.return_value = router_response

        transport = BoundedAudioTransport(
            stt_provider=stt_provider,
            router_dispatch=router_dispatch,
            tts_provider=tts
        )

        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [{"bytes": b"\x00\x00" * 160}, {"text": "DONE"}]
        ws_state = Mock()
        ws_state.name = "CONNECTED"
        ws.client_state = ws_state

        await transport.handle_websocket(ws, "s-prod-2", "r-prod-2")

        # Assistant text MUST still be delivered
        ws.send_json.assert_any_call({
            "type": "assistant_text",
            "session_id": "s-prod-2",
            "request_id": "r-prod-2",
            "text": "Đã bật đèn."
        })
        # Soft error for TTS delivered, no fake speaking audio event sent
        ws.send_json.assert_any_call({
            "type": "error",
            "session_id": "s-prod-2",
            "request_id": "r-prod-2",
            "error_code": "tts_unavailable",
            "detail": "Brain TTS error: brain_unavailable"
        })

    asyncio.run(run())
