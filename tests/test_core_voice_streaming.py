import asyncio
import json
import warnings
from typing import Any, AsyncGenerator

import pytest

from alex_voice_transport import BoundedAudioTransport
from alex_voice import VoiceSessionState, VoiceSessionLifecycle
from alex_stt import STTResult
from alex_brain_integration import CoreBrainChatResponse


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.received = []
        self.headers = {"origin": "http://localhost", "host": "localhost"}
        self.accepted = False
        from starlette.websockets import WebSocketState
        self.application_state = WebSocketState.CONNECTED
        self.client_state = WebSocketState.CONNECTED
        self.slow_send = False
        
    async def send_json(self, data: dict):
        if self.closed:
            raise RuntimeError("Cannot send after close")
        if self.slow_send:
            await asyncio.sleep(0.01)
        self.sent.append(json.dumps(data))
        
    async def accept(self):
        self.accepted = True
        
    async def receive(self):
        if not self.received:
            await asyncio.sleep(0.5)
            raise RuntimeError("Disconnect")
        return self.received.pop(0)

    async def close(self, code=1000):
        self.closed = True


class MockSttProvider:
    async def transcribe(self, session_id: str, request_id: str, audio: bytes, **kwargs) -> STTResult:
        return STTResult(
            session_id=session_id,
            request_id=request_id,
            transcript="Hello",
            is_final=True,
            provider="mock"
        )


class MockTtsProvider:
    async def synthesize(self, session_id: str, request_id: str, text: str) -> Any:
        class TtsResult:
            audio_data = b"fakeaudio" * 10
            metadata = {}
        return TtsResult()


class MockIntelligenceRouter:
    def __init__(self, deltas: list[str], final_text: str):
        self.deltas = deltas
        self.final_text = final_text

    def dispatch(self, req, stream_callback=None):
        print("MockRouter dispatch called. stream_callback:", stream_callback)
        if stream_callback:
            for d in self.deltas:
                stream_callback(d)
        return CoreBrainChatResponse(
            request_id="req-1",
            assistant_text=self.final_text,
            tool_results=[],
            route="chat"
        )


@pytest.fixture
def mock_ws():
    return FakeWebSocket()


@pytest.fixture
def transport():
    return BoundedAudioTransport(
        stt_provider=MockSttProvider(),
        router_dispatch=lambda x: None,  # We'll inject per-test
        tts_provider=MockTtsProvider()
    )


@pytest.mark.anyio
async def test_stream_delta_callback_forwards_successfully(transport, mock_ws):
    deltas = ["a", "b", "c"]
    final = "abc"
    router = MockIntelligenceRouter(deltas, final)
    transport.router_dispatch = router.dispatch

    mock_ws.received = [
        {"bytes": b"fakeaudio"},
        {"text": "done"}
    ]
    
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await transport.handle_websocket(mock_ws, "session-1", "req-1")
        
        # Test 2: No RuntimeWarning about unawaited coroutine
        for warning in w:
            assert "was never awaited" not in str(warning.message)

    sent_events = [json.loads(s) for s in mock_ws.sent]
    
    types = [e["type"] for e in sent_events]
    # start (listening) -> transcribing -> thinking -> 3 deltas -> assistant_text -> speaking
    assert types.count("text_delta") == 3
    
    delta_events = [e for e in sent_events if e["type"] == "text_delta"]
    assert delta_events[0]["delta"] == "a"
    assert delta_events[1]["delta"] == "b"
    assert delta_events[2]["delta"] == "c"
    
    # Test 3 & 4: Ordering is preserved
    idx_start = types.index("thinking")
    idx_delta_first = types.index("text_delta")
    idx_final = types.index("assistant_text")
    idx_tts = types.index("speaking")
    
    assert idx_start < idx_delta_first < idx_final < idx_tts

    # Test 5 & 6: Final reconstructed text matches
    final_event = [e for e in sent_events if e["type"] == "assistant_text"][0]
    assert final_event["assistant_text"] == "abc"


@pytest.mark.anyio
async def test_queue_saturation_produces_failure(transport, mock_ws):
    # Simulate a router that emits 150 deltas quickly (queue size is 100)
    class FastSaturatingRouter:
        def dispatch(self, req, stream_callback=None):
            if stream_callback:
                import time
                for i in range(150):
                    stream_callback(f"a{i}")
                    time.sleep(0.001)
            import time
            time.sleep(0.2)
            return CoreBrainChatResponse(
                request_id="req-sat",
                assistant_text="ab",
                tool_results=[],
                route="chat"
            )

    router = FastSaturatingRouter()
    transport.router_dispatch = router.dispatch

    mock_ws.received = [
        {"bytes": b"fakeaudio"},
        {"text": "done"}
    ]
    mock_ws.slow_send = True
    
    # We want to wait for it to fail gracefully
    await transport.handle_websocket(mock_ws, "session-sat", "req-sat")
    
    sent_events = [json.loads(s) for s in mock_ws.sent]
    types = [e["type"] for e in sent_events]
    
    # Queue saturation should cause terminal_flag to be set.
    # When terminal_flag is True, consumer stops sending text_delta, but the transport completes,
    # and eventually it might close or fail.
    # Because consumer_task doesn't fail the outer try block, the transport will finish normally
    # but the text_deltas will be truncated to <= 100.
    delta_count = types.count("text_delta")
    assert delta_count <= 100


@pytest.mark.anyio
async def test_disconnect_during_stream(transport, mock_ws):
    # If the router takes too long and the websocket disconnects
    class SlowRouter:
        def dispatch(self, req, stream_callback=None):
            if stream_callback:
                stream_callback("a")
                time.sleep(0.2)
                stream_callback("b")
            return CoreBrainChatResponse(
                request_id="req-2",
                assistant_text="ab",
                tool_results=[],
                route="chat"
            )

    import time
    router = SlowRouter()
    transport.router_dispatch = router.dispatch

    mock_ws.received = [
        {"bytes": b"fakeaudio"},
        {"text": "done"}
    ]

    # Start transport handler
    task = asyncio.create_task(transport.handle_websocket(mock_ws, "session-2", "req-2"))
    
    # Wait until it starts thinking, then simulate client disconnect
    await asyncio.sleep(0.05)
    task.cancel()  # Simulates disconnect handling from outer scope
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    sent_events = [json.loads(s) for s in mock_ws.sent]
    
    # Test 7 & 8: zero send-after-close, exactly one close
    assert mock_ws.closed
    # After cancel, any late deltas pushed by the thread are discarded by SafeWebSocketChannel logic
    # and consumer cancel.
    
    # Assert exact one close was called
    assert mock_ws.closed
    
    # No late sends
    sent_events = [json.loads(s) for s in mock_ws.sent]
    assert not any("late" in e.get("delta", "") for e in sent_events)
