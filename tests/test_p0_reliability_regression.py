import asyncio
import threading
import pytest

from alex_voice import VoiceSessionLifecycle, VoiceInput, process_voice_transcript, VoiceSessionState
from alex_brain_client import CoreBrainClient, CoreBrainConfig, BrainClientError
from brain_service.service import BrainInferenceService, BrainChatRequest
from brain_service.provider import BrainTextProvider, ProviderReply, EmptyGenerationError, ProviderToolProposal


class BlockableProvider(BrainTextProvider):
    name = "blockable"
    configured = True
    supports_warmup = True

    def __init__(self):
        self.entry_event = threading.Event()
        self.release_event = threading.Event()

    def warmup(self, *, timeout_seconds, system_instruction, tools):
        pass

    def infer(self, *, system_instruction, user_text, tools, generation_budget=None):
        self.entry_event.set()
        self.release_event.wait()
        return ProviderReply(assistant_text="I am done", tool_calls=[])

def test_brain_admission_gate_fast_fail():
    provider = BlockableProvider()
    service = BrainInferenceService(provider)

    # Start request A in a thread
    exceptions = []
    def run_a():
        req = BrainChatRequest(request_id="req-a", user_text="heavy", allowed_tools=["system_status"])
        try:
            service.chat(req)
        except Exception as e:
            exceptions.append(e)

    t = threading.Thread(target=run_a)
    t.start()

    try:
        # Wait until A is inside the provider
        assert provider.entry_event.wait(timeout=5.0), "Provider did not enter in time"

        # Request B should fail fast
        req_b = BrainChatRequest(request_id="req-b", user_text="heavy", allowed_tools=["system_status"])
        from brain_service.service import InferenceBusyError
        with pytest.raises(InferenceBusyError):
            service.chat(req_b)

        # Health and readiness should still work
        health = service.health()
        assert health.status == "ok"
    finally:
        # Release A
        provider.release_event.set()
        t.join(timeout=5.0)
        assert not t.is_alive(), "Thread A did not terminate"
        if exceptions:
            raise exceptions[0]

def test_brain_blank_no_tool_rejects():
    class BlankProvider(BrainTextProvider):
        name = "blank"
        configured = True
        supports_warmup = True
        def warmup(self, *, timeout_seconds, system_instruction, tools): pass
        def infer(self, *, system_instruction, user_text, tools, generation_budget=None):
            return ProviderReply(assistant_text="   \n  ", tool_calls=[])

    service = BrainInferenceService(BlankProvider())
    req = BrainChatRequest(request_id="req-1", user_text="heavy", allowed_tools=["system_status"])
    with pytest.raises(EmptyGenerationError):
        service.chat(req)

def test_brain_valid_tool_only_accepted():
    class ToolOnlyProvider(BrainTextProvider):
        name = "tool_only"
        configured = True
        supports_warmup = True
        def warmup(self, *, timeout_seconds, system_instruction, tools): pass
        def infer(self, *, system_instruction, user_text, tools, generation_budget=None):
            call = ProviderToolProposal(name="system_status", arguments="{}")
            return ProviderReply(assistant_text="  ", tool_calls=[call])

    service = BrainInferenceService(ToolOnlyProvider())
    req = BrainChatRequest(request_id="req-1", user_text="heavy", allowed_tools=["system_status"])
    res = service.chat(req)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "system_status"

def test_voice_mutation_classification():
    from alex_brain_integration import CoreBrainChatResponse, CoreBrainToolResult
    class MockRouter:
        def __init__(self, tool_name):
            self.tool_name = tool_name
        def dispatch(self, request):
            from alex_brain_tools import BrainToolCall
            call = BrainToolCall(name=self.tool_name, arguments={}) if self.tool_name else None
            return CoreBrainChatResponse(
                request_id="req-1",
                route="brain_inference",
                assistant_text="Doing it",
                tool_results=[CoreBrainToolResult(name=call.name, status="completed", result={"outcome": "success"})] if call else []
            )

    # Read-only
    session = VoiceSessionLifecycle("sess-1")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    voice_input = VoiceInput(session_id="sess-1", request_id="req-1", transcript="test", is_final=True, source="test", created_at="now")

    res = process_voice_transcript(session, voice_input, MockRouter("system_status"))
    assert res.state == VoiceSessionState.THINKING

    # Mutation
    session2 = VoiceSessionLifecycle("sess-2")
    session2.transition_to(VoiceSessionState.LISTENING)
    session2.transition_to(VoiceSessionState.TRANSCRIBING)
    voice_input2 = VoiceInput(session_id="sess-2", request_id="req-2", transcript="test", is_final=True, source="test", created_at="now")

    class MutationRouter:
        def dispatch(self, request):
            from alex_brain_tools import BrainToolCall
            call = BrainToolCall(name="set_test_led", arguments={"value": True})
            return CoreBrainChatResponse(
                request_id="req-2",
                route="brain_inference",
                assistant_text="Doing it",
                tool_results=[CoreBrainToolResult(name=call.name, status="completed", result={"outcome": "success"})]
            )

    res2 = process_voice_transcript(session2, voice_input2, MutationRouter())
    assert res2.state == VoiceSessionState.ACTING

def test_core_brain_client_busy_parsing():
    import io
    from urllib.error import HTTPError

    config = CoreBrainConfig(enabled=True, url="http://localhost:8090", client_key="secret")

    def mock_urlopen(request, timeout):
        body = b'{"error": {"code": "brain_busy", "message": "Busy"}}'
        fp = io.BytesIO(body)
        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, fp)

    client = CoreBrainClient(config, opener=mock_urlopen)

    req = BrainChatRequest(request_id="req-1", user_text="heavy", allowed_tools=["system_status"])
    with pytest.raises(BrainClientError) as exc:
        client.chat(req)

    assert exc.value.code == "brain_busy"

def test_heavy_dispatch_doesnt_block():
    async def run_test():
        from unittest.mock import Mock, AsyncMock
        from fastapi import WebSocket
        from starlette.websockets import WebSocketState
        from alex_voice_transport import BoundedAudioTransport
        from alex_stt import STTResult
        from alex_brain_integration import CoreBrainChatResponse

        stt_provider = AsyncMock()
        stt_provider.transcribe.return_value = STTResult(
            session_id="sess", request_id="req", transcript="test", is_final=True, provider="test"
        )

        class BlockingRouter:
            def __init__(self):
                self.entry_event = threading.Event()
                self.release_event = threading.Event()

            def dispatch(self, req):
                self.entry_event.set()
                self.release_event.wait()
                return CoreBrainChatResponse(request_id="req", route="test", assistant_text="done", tool_results=[])

        router = BlockingRouter()
        transport = BoundedAudioTransport(stt_provider, router.dispatch)

        ws = AsyncMock(spec=WebSocket)
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:8000"}
        ws.receive.side_effect = [
            {"bytes": b"audio_data"},
            {"text": "DONE"}
        ]
        ws.application_state = WebSocketState.CONNECTED
        ws.client_state = WebSocketState.CONNECTED

        dispatch_task = asyncio.create_task(
            transport.handle_websocket(ws, "sess", "req")
        )

        try:
            # Wait for dispatch to enter the block
            entered = await asyncio.to_thread(router.entry_event.wait, 5.0)
            assert entered, "Dispatcher did not enter blocking state in time"

            async_progress = asyncio.Event()
            async def cheap_coroutine():
                async_progress.set()

            asyncio.create_task(cheap_coroutine())

            # This should complete instantly if the event loop is not blocked
            try:
                await asyncio.wait_for(async_progress.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pytest.fail("Event loop is blocked by heavy dispatch")

            assert async_progress.is_set()

        finally:
            router.release_event.set()
            await dispatch_task

    asyncio.run(run_test())

def test_voice_valid_blank_read_only_tool_not_empty():
    from alex_brain_integration import CoreBrainChatResponse, CoreBrainToolResult

    class ReadOnlyRouter:
        def dispatch(self, request):
            from alex_brain_tools import BrainToolCall
            call = BrainToolCall(name="system_status", arguments={})
            return CoreBrainChatResponse(
                request_id="req-1",
                route="brain_inference",
                assistant_text="", # BLANK assistant text with valid tool
                tool_results=[CoreBrainToolResult(name=call.name, status="completed", result={"outcome": "success"})]
            )

    session = VoiceSessionLifecycle("sess-1")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    voice_input = VoiceInput(session_id="sess-1", request_id="req-1", transcript="test", is_final=True, source="test", created_at="now")

    res = process_voice_transcript(session, voice_input, ReadOnlyRouter())

    # It must not be treated as empty_response
    assert res.state == VoiceSessionState.THINKING
    assert res.error_code is None

def test_intelligence_router_error_observation_mapping():
    from alex_intelligence_router import IntelligenceRouter
    from alex_brain_client import BrainClientError
    from unittest.mock import Mock

    core_brain_integration = Mock()
    # Let chat throw a BrainClientError
    core_brain_integration.chat.side_effect = BrainClientError("brain_busy")

    observations = []
    def route_sink(obs):
        observations.append(obs)

    router = IntelligenceRouter(
        core_brain_integration=core_brain_integration,
        fast_path_evaluator=Mock(return_value=None),
        shadow_observer=Mock(),
        brain_request_builder=lambda p, r: p,
        brain_chat_executor=core_brain_integration.chat,
        fast_path_enabled=lambda: False,
        action_fast_path_enabled=lambda: False,
        shadow_enabled=lambda: False,
        audit_logger=Mock(),
        route_observation_sink=route_sink
    )

    from alex_brain_tools import BrainChatRequest
    req = BrainChatRequest(request_id="req-1", user_text="heavy")

    with pytest.raises(BrainClientError):
        router.dispatch(req)

    assert len(observations) == 1
    assert observations[0].error_code == "brain_busy"
    assert observations[0].success is False

def test_app_py_v1_brain_chat_http_error_mappings():
    import os
    os.environ["MQTT_PASSWORD"] = "test"
    os.environ["ALEX_API_KEY"] = "test"
    from app import v1_brain_chat, intelligence_router
    from alex_brain_client import BrainClientError
    from alex_brain_tools import BrainChatRequest
    from fastapi import HTTPException
    from unittest.mock import patch

    with patch.object(intelligence_router, "dispatch") as mock_dispatch:
        req = BrainChatRequest(request_id="r1", user_text="hello")

        # Test empty_generation -> 502
        mock_dispatch.side_effect = BrainClientError("empty_generation")
        with pytest.raises(HTTPException) as exc:
            v1_brain_chat(req)
        assert exc.value.status_code == 502
        assert exc.value.detail["code"] == "empty_generation"

        # Test brain_busy -> 503
        mock_dispatch.side_effect = BrainClientError("brain_busy")
        with pytest.raises(HTTPException) as exc:
            v1_brain_chat(req)
        assert exc.value.status_code == 503
        assert exc.value.detail["code"] == "brain_busy"

        # Test invalid_generation -> 502
        mock_dispatch.side_effect = BrainClientError("invalid_generation")
        with pytest.raises(HTTPException) as exc:
            v1_brain_chat(req)
        assert exc.value.status_code == 502
        assert exc.value.detail["code"] == "invalid_generation"

        # Test provider_error -> 502
        mock_dispatch.side_effect = BrainClientError("provider_error")
        with pytest.raises(HTTPException) as exc:
            v1_brain_chat(req)
        assert exc.value.status_code == 502
        assert exc.value.detail["code"] == "provider_error"

def test_brain_service_provider_error_mapping():
    from brain_service.app import create_app, BrainHttpError
    from brain_service.provider import ProviderUnavailableError, ProviderNotConfiguredError, ProviderTimeoutError
    from brain_service.service import BrainInferenceService
    from alex_brain_tools import BrainChatRequest
    from unittest.mock import Mock
    from brain_service.config import BrainServiceConfig
    import pytest

    mock_service = Mock(spec=BrainInferenceService)
    mock_service.provider_name = "test_provider"

    config = BrainServiceConfig(api_key="test")
    app = create_app(config=config, inference_service=mock_service)

    chat_endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == "/v1/chat" and "POST" in getattr(route, "methods", [])
    )

    req = BrainChatRequest(request_id="r1", user_text="hello")

    # 1. ProviderUnavailableError
    mock_service.chat.side_effect = ProviderUnavailableError()
    with pytest.raises(BrainHttpError) as exc:
        chat_endpoint(payload=req, _=None)
    assert exc.value.status_code == 503
    assert exc.value.code == "provider_error"

    # 2. ProviderNotConfiguredError
    mock_service.chat.side_effect = ProviderNotConfiguredError()
    with pytest.raises(BrainHttpError) as exc:
        chat_endpoint(payload=req, _=None)
    assert exc.value.status_code == 503
    assert exc.value.code == "provider_error"

    # 3. ProviderTimeoutError
    mock_service.chat.side_effect = ProviderTimeoutError()
    with pytest.raises(BrainHttpError) as exc:
        chat_endpoint(payload=req, _=None)
    assert exc.value.status_code == 504
    assert exc.value.code == "brain_timeout"

def test_voice_success_telemetry_valid_json():
    import json
    from alex_voice import process_voice_transcript, VoiceSessionLifecycle, VoiceInput
    from alex_brain_integration import CoreBrainChatResponse, CoreBrainToolResult
    
    class FakeRouter:
        def dispatch(self, request):
            return CoreBrainChatResponse(request_id="r1", assistant_text="done", route="test", tool_results=[])
            
    session = VoiceSessionLifecycle("sess-log")
    import time
    v_in = VoiceInput(
        session_id="sess-log",
        request_id="req-log",
        transcript="hello",
        is_final=True,
        source="local_mic",
        created_at=str(time.time())
    )
    
    import logging
    telemetry_logger = logging.getLogger("alex.intelligence.telemetry")
    
    # We want to catch the exact JSON string
    log_records = []
    class ListHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record.getMessage())
            
    handler = ListHandler()
    telemetry_logger.addHandler(handler)
    try:
        from alex_voice import VoiceSessionState
        session.transition_to(VoiceSessionState.LISTENING)
        session.transition_to(VoiceSessionState.TRANSCRIBING)
        process_voice_transcript(session, v_in, FakeRouter())
        
        success_logs = [m for m in log_records if "voice_process_success" in m]
        assert len(success_logs) == 1
        
        # Must be valid JSON
        parsed = json.loads(success_logs[0])
        assert parsed["event"] == "voice_process_success"
        # "false" (string in Python formatting) -> valid JSON boolean `false` if not quoted in the format string.
        # Wait, the format string in alex_voice.py is:
        # '{"event": ..., "is_action": %s}'
        # If we pass "false" to %s, it becomes '... "is_action": false}' which is valid JSON.
        assert parsed["is_action"] is False
        assert "duration_ms" in parsed
    finally:
        telemetry_logger.removeHandler(handler)
