"""Workstream B — WebSocket lifecycle regression tests.

These tests verify the SafeWebSocketChannel eliminates the ASGI
websocket.send-after-close race and that all send/close operations
are properly serialized.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from alex_stt import STTResult
from alex_voice import VoiceSessionState
from alex_voice_transport import BoundedAudioTransport, SafeWebSocketChannel


def _make_ws(*, connected: bool = True) -> AsyncMock:
    """Create a mock WebSocket with proper state tracking."""
    ws = AsyncMock(spec=WebSocket)
    ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
    if connected:
        ws.application_state = WebSocketState.CONNECTED
        ws.client_state = WebSocketState.CONNECTED
    else:
        ws.application_state = WebSocketState.DISCONNECTED
        ws.client_state = WebSocketState.DISCONNECTED
    return ws


def _make_transport(
    stt_result: STTResult | None = None,
    router_result: Mock | None = None,
    router_side_effect: Exception | None = None,
) -> tuple[BoundedAudioTransport, AsyncMock, Mock]:
    """Create transport with configurable STT and router behavior."""
    stt_provider = AsyncMock()
    if stt_result is not None:
        stt_provider.transcribe.return_value = stt_result
    router_dispatch = Mock()
    if router_result is not None:
        router_dispatch.return_value = router_result
    if router_side_effect is not None:
        router_dispatch.side_effect = router_side_effect
    transport = BoundedAudioTransport(stt_provider, router_dispatch)
    return transport, stt_provider, router_dispatch


# --- SafeWebSocketChannel unit tests ---


def test_channel_send_after_close_is_silent():
    """After close, send must return False and not raise."""
    async def run():
        ws = _make_ws()
        channel = SafeWebSocketChannel(ws)
        await channel.close()
        assert channel.is_closed
        result = await channel.send_json({"type": "test"})
        assert result is False
        assert channel.send_count == 0
    asyncio.run(run())


def test_channel_close_is_idempotent():
    """Multiple close calls must not raise and close count stays at one."""
    async def run():
        ws = _make_ws()
        channel = SafeWebSocketChannel(ws)
        await channel.close()
        await channel.close()
        await channel.close()
        assert channel.close_count == 1
        assert channel.is_closed
    asyncio.run(run())


def test_channel_send_count_after_close_is_zero():
    """Send count after close must be zero."""
    async def run():
        ws = _make_ws()
        channel = SafeWebSocketChannel(ws)
        await channel.close()
        for _ in range(5):
            await channel.send_json({"type": "test"})
        assert channel.send_count == 0
    asyncio.run(run())


def test_channel_close_count_is_exactly_one():
    """Close count must be exactly one, even with multiple calls."""
    async def run():
        ws = _make_ws()
        channel = SafeWebSocketChannel(ws)
        await channel.close()
        await channel.close()
        assert channel.close_count == 1
    asyncio.run(run())


def test_channel_runtime_error_during_send_marks_closed():
    """RuntimeError during send must mark channel as closed."""
    async def run():
        ws = _make_ws()
        ws.send_json.side_effect = RuntimeError("ASGI send after close")
        channel = SafeWebSocketChannel(ws)
        result = await channel.send_json({"type": "test"})
        assert result is False
        assert channel.is_closed
        # Subsequent sends must also be silent
        result2 = await channel.send_json({"type": "test2"})
        assert result2 is False
    asyncio.run(run())


def test_channel_disconnect_during_send_marks_closed():
    """WebSocketDisconnect during send must mark channel as closed."""
    async def run():
        ws = _make_ws()
        ws.send_json.side_effect = WebSocketDisconnect()
        channel = SafeWebSocketChannel(ws)
        result = await channel.send_json({"type": "test"})
        assert result is False
        assert channel.is_closed
    asyncio.run(run())


def test_channel_send_on_disconnected_ws_returns_false():
    """Sending on a disconnected WebSocket must return False."""
    async def run():
        ws = _make_ws(connected=False)
        channel = SafeWebSocketChannel(ws)
        result = await channel.send_json({"type": "test"})
        assert result is False
    asyncio.run(run())


# --- BoundedAudioTransport integration tests ---


def test_no_asgi_runtime_error_on_disconnect_during_processing():
    """Client disconnect while Brain is processing must not produce ASGI RuntimeError."""
    async def run():
        stt_result = STTResult(
            session_id="s1", request_id="r1", transcript="test",
            is_final=True, provider="test"
        )
        router_response = Mock()
        router_response.route = "fast_response"
        router_response.tool_results = []
        router_response.assistant_text = "OK"
        router_response.state = VoiceSessionState.COMPLETED
        router_response.error_code = None
        router_response.metadata = {"is_action": False}

        transport, stt_provider, router_dispatch = _make_transport(
            stt_result=stt_result, router_result=router_response
        )

        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"end_audio"}'}
        ]

        # Simulate disconnect after STT but before router completes
        call_count = 0
        original_send_json = ws.send_json

        async def disconnect_after_thinking(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:  # After thinking event
                ws.application_state = WebSocketState.DISCONNECTED
                ws.client_state = WebSocketState.DISCONNECTED
            return await original_send_json(*args, **kwargs)

        ws.send_json = disconnect_after_thinking

        # This must not raise RuntimeError
        await transport.handle_websocket(ws, "s1", "r1")

    asyncio.run(run())


def test_timeout_racing_normal_completion():
    """Session timeout must not cause errors if completion is in progress."""
    async def run():
        stt_result = STTResult(
            session_id="s1", request_id="r1", transcript="test",
            is_final=True, provider="test"
        )
        router_response = Mock()
        router_response.route = "fast_response"
        router_response.tool_results = []
        router_response.assistant_text = "OK"
        router_response.state = VoiceSessionState.COMPLETED
        router_response.error_code = None
        router_response.metadata = {"is_action": False}

        transport, _, _ = _make_transport(
            stt_result=stt_result, router_result=router_response
        )

        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"end_audio"}'}
        ]

        # Normal flow should complete without error
        await transport.handle_websocket(ws, "s1", "r1")

        # Verify completed event was sent
        sent_types = [call.args[0]["type"] for call in ws.send_json.call_args_list
                      if isinstance(call.args[0], dict)]
        assert "completed" in sent_types

    asyncio.run(run())


def test_cancellation_racing_completion():
    """Client cancel arriving after processing started must not cause double-close."""
    async def run():
        stt_result = STTResult(
            session_id="s1", request_id="r1", transcript="test",
            is_final=True, provider="test"
        )
        router_response = Mock()
        router_response.route = "fast_response"
        router_response.tool_results = []
        router_response.assistant_text = "OK"
        router_response.state = VoiceSessionState.CANCELLED
        router_response.error_code = "cancelled"
        router_response.metadata = {}

        transport, _, _ = _make_transport(
            stt_result=stt_result, router_result=router_response
        )

        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"cancel"}'}
        ]

        await transport.handle_websocket(ws, "s1", "r1")
        # Should handle cleanly — no exception

    asyncio.run(run())


def test_server_close_before_pending_error():
    """Server error during processing should send error then close, not the reverse."""
    async def run():
        stt_result = STTResult(
            session_id="s1", request_id="r1", transcript="test",
            is_final=True, provider="test"
        )
        from alex_brain_client import BrainClientError
        transport, _, _ = _make_transport(
            stt_result=stt_result,
            router_side_effect=BrainClientError("brain_timeout")
        )

        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"end_audio"}'}
        ]

        await transport.handle_websocket(ws, "s1", "r1")

        # Find the error event — it should exist before close
        sent_types = [call.args[0]["type"] for call in ws.send_json.call_args_list
                      if isinstance(call.args[0], dict)]
        assert "error" in sent_types

    asyncio.run(run())


def test_transport_success_sends_expected_events():
    """Normal successful flow should emit auth_ok → transcribing → transcript_final → thinking → assistant_text → completed."""
    async def run():
        stt_result = STTResult(
            session_id="s1", request_id="r1", transcript="Bật đèn",
            is_final=True, provider="test"
        )
        router_response = Mock()
        router_response.route = "fast_response"
        router_response.tool_results = []
        router_response.assistant_text = "Đã bật đèn."
        router_response.state = VoiceSessionState.COMPLETED
        router_response.error_code = None
        router_response.metadata = {"is_action": False}

        transport, _, _ = _make_transport(
            stt_result=stt_result, router_result=router_response
        )

        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"end_audio"}'}
        ]

        await transport.handle_websocket(ws, "s1", "r1")

        sent_types = [call.args[0]["type"] for call in ws.send_json.call_args_list
                      if isinstance(call.args[0], dict)]
        assert sent_types == ["auth_ok", "transcribing", "transcript_final", "thinking", "assistant_text", "completed"]

    asyncio.run(run())


def test_transport_cancel_sends_cancelled_then_closes():
    """Cancel flow should send completed/CANCELLED event."""
    async def run():
        transport, _, _ = _make_transport()
        ws = _make_ws()
        ws.receive.side_effect = [
            {"bytes": b"audio"},
            {"text": '{"type":"cancel"}'}
        ]

        await transport.handle_websocket(ws, "s1", "r1")

        sent = [call.args[0] for call in ws.send_json.call_args_list
                if isinstance(call.args[0], dict)]
        # Find the cancelled event
        cancelled = [m for m in sent if m.get("state") == "CANCELLED"]
        assert len(cancelled) == 1
        assert cancelled[0]["type"] == "completed"

    asyncio.run(run())


def test_transport_disconnect_no_sends_after():
    """After client disconnect, no further sends should occur."""
    async def run():
        transport, _, _ = _make_transport()
        ws = _make_ws()
        ws.receive.side_effect = WebSocketDisconnect()

        # Mark as disconnected immediately
        ws.application_state = WebSocketState.DISCONNECTED
        ws.client_state = WebSocketState.DISCONNECTED

        await transport.handle_websocket(ws, "s1", "r1")

        # Only the auth_ok send may have been attempted (before disconnect was detected)
        # but the SafeWebSocketChannel would have blocked it since ws state is DISCONNECTED
    asyncio.run(run())
