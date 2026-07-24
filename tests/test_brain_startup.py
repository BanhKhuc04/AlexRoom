from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from alex_brain_client import MAX_BRAIN_TIMEOUT_SECONDS
from alex_brain_tools import (
    TOOL_NAMES,
    BrainChatRequest,
    BrainRelevantContext,
)
from brain_service.app import AUTH_HEADER, create_app
from brain_service.config import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_WARMUP_TIMEOUT_SECONDS,
    MAX_PROVIDER_TIMEOUT_SECONDS,
    MAX_WARMUP_TIMEOUT_SECONDS,
    BrainServiceConfig,
)
from brain_service.provider import (
    InvalidProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SYSTEM_INSTRUCTION,
)
from brain_service.providers.ollama_native import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_WARMUP_NUM_PREDICT,
    OllamaNativeProvider,
)
from brain_service.service import BrainInferenceService
from _brain_service_test_client import AsgiTestClient


ROOT = Path(__file__).resolve().parents[1]
TEST_BRAIN_KEY = "startup-test-key"
TEST_PROVIDER_KEY = "provider-secret-never-log"


class RecordingTransport:
    def __init__(
        self,
        responses: list[dict[str, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(
            responses
            or [
                {
                    "done": True,
                    "message": {"role": "assistant", "content": ""},
                }
            ]
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    def post_json(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def provider(
    transport: RecordingTransport,
    *,
    model: str = "qwen3.5:2b",
) -> OllamaNativeProvider:
    return OllamaNativeProvider(
        base_url="http://127.0.0.1:11434",
        model=model,
        api_key=TEST_PROVIDER_KEY,
        timeout_seconds=25,
        transport=transport,
    )


def config(**changes: object) -> BrainServiceConfig:
    values = {
        "api_key": TEST_BRAIN_KEY,
        "provider": "ollama_native",
        "provider_url": "http://127.0.0.1:11434",
        "provider_model": "qwen3.5:2b",
        "provider_timeout_seconds": 25,
        "warmup_timeout_seconds": 60,
    }
    values.update(changes)
    return BrainServiceConfig(**values)


def run_lifespan(app) -> None:
    async def enter() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(enter())


def test_warmup_uses_configured_model_and_bounded_timeout() -> None:
    transport = RecordingTransport()
    service = BrainInferenceService(provider(transport))

    readiness = service.warmup(timeout_seconds=60)

    assert readiness.ready is True
    assert readiness.warmup == "ready"
    call = transport.calls[0]
    assert call["timeout_seconds"] == 60
    assert call["payload"]["model"] == "qwen3.5:2b"


def test_warmup_has_no_user_text_tools_or_execution_surface() -> None:
    transport = RecordingTransport()
    service = BrainInferenceService(provider(transport))

    service.warmup(timeout_seconds=60)

    payload = transport.calls[0]["payload"]
    assert "messages" not in payload
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["keep_alive"] == OLLAMA_KEEP_ALIVE == -1
    assert payload["options"]["num_predict"] == OLLAMA_WARMUP_NUM_PREDICT
    assert "tools" not in payload
    assert "tool_calls" not in payload
    assert "user" not in json.dumps(payload).lower()


def test_normal_inference_keeps_model_resident() -> None:
    transport = RecordingTransport(
        responses=[
            {"message": {"content": "ok", "tool_calls": []}},
        ]
    )
    provider(transport).infer(
        system_instruction=SYSTEM_INSTRUCTION,
        user_text="Kiểm tra.",
        tools=[],
    )
    assert transport.calls[0]["payload"]["keep_alive"] == -1


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (ProviderTimeoutError("secret-timeout"), "provider_timeout"),
        (
            ProviderUnavailableError("secret-unavailable"),
            "provider_unavailable",
        ),
        (
            InvalidProviderResponseError("secret-malformed"),
            "invalid_provider_response",
        ),
        (RuntimeError("secret-unexpected"), "warmup_failed"),
    ),
)
def test_warmup_failure_is_bounded_degraded_and_sanitized(
    error: Exception,
    reason: str,
) -> None:
    service = BrainInferenceService(
        provider(RecordingTransport(error=error))
    )

    readiness = service.warmup(timeout_seconds=60)

    assert readiness.status == "degraded"
    assert readiness.ready is False
    assert readiness.warmup == "degraded"
    assert readiness.reason == reason
    assert "secret" not in readiness.model_dump_json()


def test_malformed_warmup_response_is_degraded() -> None:
    service = BrainInferenceService(
        provider(RecordingTransport(responses=[{"done": False}]))
    )
    readiness = service.warmup(timeout_seconds=60)
    assert readiness.reason == "invalid_provider_response"
    assert readiness.ready is False


def test_provider_not_configured_is_safe_and_makes_no_request() -> None:
    transport = RecordingTransport()
    service = BrainInferenceService(provider(transport, model=""))
    readiness = service.warmup(timeout_seconds=60)
    assert readiness.warmup == "not_configured"
    assert readiness.ready is False
    assert transport.calls == []


def test_lifespan_warms_once_then_normal_request_runs_once() -> None:
    transport = RecordingTransport(
        responses=[
            {
                "done": True,
                "message": {"role": "assistant", "content": ""},
            },
            {"message": {"content": "Đã hiểu.", "tool_calls": []}},
        ]
    )
    service = BrainInferenceService(provider(transport))
    app = create_app(config(), service)

    run_lifespan(app)
    response = AsgiTestClient(app).post(
        "/v1/chat",
        headers={AUTH_HEADER: TEST_BRAIN_KEY},
        json_body={
            "request_id": "req-after-warmup",
            "user_text": "Kiểm tra hệ thống.",
        },
    )

    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Đã hiểu."
    assert len(transport.calls) == 2
    assert "messages" not in transport.calls[0]["payload"]
    assert len(transport.calls[1]["payload"]["messages"]) == 2


def test_health_stays_backward_compatible_and_ready_is_additive() -> None:
    service = BrainInferenceService(
        provider(RecordingTransport())
    )
    app = create_app(config(), service)
    client = AsgiTestClient(app)

    assert client.get("/health").json() == {
        "status": "ok",
        "service": "alex-brain",
        "api_version": "v1",
        "provider": "configured",
    }
    assert client.get("/ready").json()["warmup"] == "not_started"

    run_lifespan(app)
    ready = client.get("/ready").json()
    assert ready["status"] == "ready"
    assert ready["ready"] is True
    assert ready["warmup"] == "ready"


def test_legacy_and_narrowed_requests_remain_unchanged() -> None:
    transport = RecordingTransport(
        responses=[
            {"message": {"content": "legacy", "tool_calls": []}},
            {"message": {"content": "narrowed", "tool_calls": []}},
        ]
    )
    service = BrainInferenceService(provider(transport))

    legacy = service.chat(
        BrainChatRequest(
            request_id="req-legacy",
            user_text="Kiểm tra hệ thống.",
        )
    )
    narrowed = service.chat(
        BrainChatRequest(
            request_id="req-narrowed",
            user_text="Kiểm tra hệ thống.",
            allowed_tools=["system_status"],
        )
    )

    assert legacy.assistant_text == "legacy"
    assert narrowed.assistant_text == "narrowed"
    assert transport.calls[0]["payload"]["messages"][0]["content"] == (
        SYSTEM_INSTRUCTION
    )
    legacy_tools = transport.calls[0]["payload"]["tools"]
    narrowed_tools = transport.calls[1]["payload"]["tools"]
    assert tuple(item["function"]["name"] for item in legacy_tools) == (
        TOOL_NAMES
    )
    assert [
        item["function"]["name"] for item in narrowed_tools
    ] == ["system_status"]


def test_enhanced_zero_tools_request_remains_zero_tools() -> None:
    transport = RecordingTransport(
        responses=[{"message": {"content": "context", "tool_calls": []}}]
    )
    service = BrainInferenceService(provider(transport))
    context = BrainRelevantContext.model_validate(
        {
            "context_schema_version": 1,
            "knowledge_schema_version": 1,
            "snapshot_captured_at": "2026-07-24T00:00:00Z",
            "scope": "general",
            "reason": "no_relevant_knowledge",
            "incomplete": False,
            "sources": [],
            "sections": [],
        }
    )

    response = service.chat(
        BrainChatRequest(
            request_id="req-context-zero",
            user_text="Câu hỏi không cần tool.",
            allowed_tools=[],
            context=context,
        )
    )

    assert response.tool_calls == []
    assert "tools" not in transport.calls[0]["payload"]
    assert "<alex_core_context>" in (
        transport.calls[0]["payload"]["messages"][0]["content"]
    )


@pytest.mark.parametrize(
    "raw",
    ("0", "-1", "25.001", "90", "nan", "inf", "not-a-number"),
)
def test_provider_timeout_rejects_invalid_or_over_budget_values(
    raw: str,
) -> None:
    with patch.dict(
        "os.environ",
        {"ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS": raw},
        clear=True,
    ):
        with pytest.raises(ValueError):
            BrainServiceConfig.from_environment()


@pytest.mark.parametrize("raw", ("0.1", "12.5", "25"))
def test_provider_timeout_accepts_bounded_values(raw: str) -> None:
    with patch.dict(
        "os.environ",
        {"ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS": raw},
        clear=True,
    ):
        parsed = BrainServiceConfig.from_environment()
    assert parsed.provider_timeout_seconds == float(raw)


def test_timeout_defaults_and_warmup_boundaries() -> None:
    with patch.dict("os.environ", {}, clear=True):
        defaults = BrainServiceConfig.from_environment()
    assert defaults.provider_timeout_seconds == (
        DEFAULT_PROVIDER_TIMEOUT_SECONDS
    )
    assert defaults.warmup_timeout_seconds == DEFAULT_WARMUP_TIMEOUT_SECONDS
    assert MAX_PROVIDER_TIMEOUT_SECONDS < MAX_BRAIN_TIMEOUT_SECONDS

    with patch.dict(
        "os.environ",
        {
            "ALEX_BRAIN_WARMUP_TIMEOUT_SECONDS": str(
                MAX_WARMUP_TIMEOUT_SECONDS
            )
        },
        clear=True,
    ):
        assert BrainServiceConfig.from_environment().warmup_timeout_seconds == (
            MAX_WARMUP_TIMEOUT_SECONDS
        )


def test_deployment_config_enforces_model_and_timeout_hierarchy() -> None:
    env_text = (
        ROOT / "deploy" / "alex-brain.env.example"
    ).read_text(encoding="utf-8")
    assert "ALEX_BRAIN_MODEL=qwen3.5:2b" in env_text
    assert "ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS=25" in env_text
    assert "ALEX_BRAIN_WARMUP_TIMEOUT_SECONDS=60" in env_text
    assert "ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS=90" not in env_text
    assert "qwen3.5:4b" not in env_text


def test_systemd_orders_after_ollama_without_restart_storm() -> None:
    unit = (
        ROOT / "deploy" / "alex-brain.service"
    ).read_text(encoding="utf-8")
    assert "After=network-online.target ollama.service" in unit
    assert "Wants=network-online.target ollama.service" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=10" in unit
    assert "StartLimitBurst=3" in unit
    assert "Requires=ollama.service" not in unit


def test_startup_files_contain_no_secret_or_execution_boundary() -> None:
    paths = (
        ROOT / "brain_service",
        ROOT / "deploy" / "alex-brain.env.example",
        ROOT / "deploy" / "alex-brain.service",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for item in paths
        for path in (
            item.rglob("*.py")
            if item.is_dir()
            else (item,)
        )
    )
    forbidden = (
        "paho.mqtt",
        "alex_hardware",
        "CommandGateway",
        "relay_1=set",
        "ALEX_BRAIN_API_KEY=secret",
        TEST_PROVIDER_KEY,
    )
    assert all(marker not in source for marker in forbidden)
