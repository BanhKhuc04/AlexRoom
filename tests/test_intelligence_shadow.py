from __future__ import annotations

import ast
import json
import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
import alex_intelligence_shadow as shadow_module  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_client import BrainClientError  # noqa: E402
from alex_brain_integration import (  # noqa: E402
    CoreBrainChatResponse,
    CoreBrainToolResult,
)
from alex_brain_resilience import (  # noqa: E402
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainFailureKind,
    BrainFailureReason,
)
from alex_brain_tools import BrainToolCall  # noqa: E402
from alex_intelligence_runtime import (  # noqa: E402
    IntelligenceRuntimeDecision,
    RuntimeOutcome,
)
from alex_intelligence_shadow import (  # noqa: E402
    IntelligenceShadowResult,
    ShadowStatus,
    intelligence_shadow_enabled,
    observe_intelligence_shadow,
)
from alex_knowledge import build_system_knowledge_snapshot  # noqa: E402
from alex_safety import CapabilityRegistry, SafetyPolicy  # noqa: E402


CAPTURED_AT = "2026-07-24T10:00:00+00:00"
OBSERVED_AT = "2026-07-24T09:59:00+00:00"
REQUEST_BODY = {
    "request_id": "req-shadow-test",
    "user_text": "ALEX có ổn không?",
}
AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}
CLIENT = AsgiTestClient(alex_app.app)
MODULE_PATH = Path(shadow_module.__file__)


def snapshot():
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        overall_status="healthy",
        health_report={
            "available": True,
            "status": "healthy",
            "stale": False,
            "report": {
                "status": "healthy",
                "generated_at": OBSERVED_AT,
            },
        },
        services={
            "core": {
                "status": "online",
                "available": True,
                "source": "core_runtime",
            },
            "brain": {
                "status": "online",
                "available": True,
                "observed_at": OBSERVED_AT,
                "source": "core_runtime",
            },
        },
        devices={
            "esp01": {
                "node_id": "esp01",
                "connection": "online",
                "last_seen_at": OBSERVED_AT,
                "verification_status": "basic_physical_validated",
                "hardware_verified": False,
                "capabilities": {
                    "test_led": {
                        "available": True,
                        "command_allowed": True,
                    },
                },
                "reported_state": {"test_led": {"on": False}},
                "source": "hardware_registry",
            },
        },
        runtime={
            "room_mode": "home",
            "simulator": False,
            "source": "core_runtime",
        },
    )


def evaluate(
    user_text: str,
    *,
    circuit_state: BrainCircuitBreakerState | None = None,
    factory=snapshot,
) -> IntelligenceShadowResult:
    return observe_intelligence_shadow(
        enabled=True,
        user_text=user_text,
        snapshot_factory=factory,
        circuit_state=circuit_state,
        circuit_config=BrainCircuitBreakerConfig(),
        now_monotonic=11.0,
    )


class StubLegacyService:
    def __init__(
        self,
        response: CoreBrainChatResponse | None = None,
        error: BrainClientError | None = None,
    ) -> None:
        self.response = response or CoreBrainChatResponse(
            request_id=REQUEST_BODY["request_id"],
            assistant_text="Legacy Brain response.",
        )
        self.error = error
        self.calls = 0

    def chat(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def post_with(
    *,
    enabled: bool,
    service: StubLegacyService,
    observer=None,
):
    if observer is None:
        observer = Mock()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            enabled,
        ),
        patch.object(
            alex_app,
            "_observe_intelligence_shadow",
            observer,
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body=REQUEST_BODY,
        )
    return response, observer


def test_flag_absent_is_off() -> None:
    assert intelligence_shadow_enabled({}) is False


@pytest.mark.parametrize(
    "value",
    ["false", "0", "no", "off", "", "enabled", "2"],
)
def test_flag_false_or_unrecognized_is_off(value: str) -> None:
    assert intelligence_shadow_enabled(
        {"ALEX_INTELLIGENCE_SHADOW_ENABLED": value}
    ) is False


@pytest.mark.parametrize(
    "value",
    ["true", "TRUE", "  yes ", "1", "On"],
)
def test_flag_true_values_are_deterministic(value: str) -> None:
    assert intelligence_shadow_enabled(
        {"ALEX_INTELLIGENCE_SHADOW_ENABLED": value}
    ) is True


def test_flag_parser_does_not_mutate_environment() -> None:
    environment = {"ALEX_INTELLIGENCE_SHADOW_ENABLED": "true"}
    original = dict(environment)
    assert intelligence_shadow_enabled(environment)
    assert environment == original


def test_shadow_disabled_is_completely_lazy() -> None:
    factory = Mock(side_effect=AssertionError("must not build snapshot"))
    evaluator = Mock(side_effect=AssertionError("must not run runtime"))
    observer = Mock(side_effect=AssertionError("must not observe"))
    result = observe_intelligence_shadow(
        enabled=False,
        user_text="ignored",
        snapshot_factory=factory,
        now_monotonic=0,
        evaluator=evaluator,
        observer=observer,
    )
    assert result.status is ShadowStatus.DISABLED
    factory.assert_not_called()
    evaluator.assert_not_called()
    observer.assert_not_called()


def test_shadow_enabled_evaluates_runtime_once() -> None:
    factory = Mock(return_value=snapshot())
    result = observe_intelligence_shadow(
        enabled=True,
        user_text="ALEX có ổn không?",
        snapshot_factory=factory,
        now_monotonic=0,
    )
    assert result.status is ShadowStatus.EVALUATED
    factory.assert_called_once_with()


def test_system_query_can_respond_fast() -> None:
    result = evaluate("ALEX có ổn không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.fast_response_handled is True
    assert result.would_call_brain is False


def test_device_detail_can_respond_fast() -> None:
    result = evaluate("ESP01 online không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.knowledge_scope == "device_detail"


def test_reasoning_query_records_would_call_brain_only() -> None:
    result = evaluate("Giải thích tại sao hệ thống chậm")
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.would_call_brain is True


def test_open_shadow_circuit_does_not_call_or_block_live_brain() -> None:
    state = BrainCircuitBreakerState(
        state=BrainCircuitState.OPEN,
        consecutive_failures=2,
        opened_at_monotonic=10,
        last_failure_kind=BrainFailureKind.TIMEOUT,
        last_failure_reason=BrainFailureReason.BRAIN_TIMEOUT,
    )
    result = evaluate(
        "Giải thích tại sao hệ thống chậm",
        circuit_state=state,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.would_call_brain is False
    assert result.would_be_degraded is True


def test_clarification_is_observed_but_not_activated() -> None:
    result = evaluate("bật nó lên")
    assert result.outcome is RuntimeOutcome.ASK_CLARIFICATION
    assert result.would_call_brain is False


def test_runtime_exception_normalizes_to_shadow_error() -> None:
    def fail(**_kwargs):
        raise RuntimeError("secret prompt and provider response")

    result = observe_intelligence_shadow(
        enabled=True,
        user_text="private user text",
        snapshot_factory=snapshot,
        now_monotonic=0,
        evaluator=fail,
    )
    assert result.status is ShadowStatus.SHADOW_ERROR
    assert "secret" not in json.dumps(result.to_compact_dict())


def test_malformed_snapshot_normalizes_to_shadow_error() -> None:
    result = evaluate(
        "ALEX có ổn không?",
        factory=lambda: {"schema_version": 1},
    )
    assert result.status is ShadowStatus.SHADOW_ERROR


def test_future_schema_is_bounded_and_non_executable() -> None:
    future = snapshot()
    object.__setattr__(future, "schema_version", 999)
    result = evaluate("ALEX có ổn không?", factory=lambda: future)
    assert result.status is ShadowStatus.EVALUATED
    assert result.outcome is RuntimeOutcome.UNSUPPORTED
    assert result.would_call_brain is False


def test_observer_exception_is_isolated() -> None:
    observer = Mock(side_effect=RuntimeError("observer failed"))
    result = observe_intelligence_shadow(
        enabled=True,
        user_text="ALEX có ổn không?",
        snapshot_factory=snapshot,
        now_monotonic=0,
        observer=observer,
    )
    assert result.status is ShadowStatus.EVALUATED
    observer.assert_called_once()


def test_shadow_result_is_json_serializable() -> None:
    encoded = json.dumps(evaluate("ALEX có ổn không?").to_compact_dict())
    assert '"status": "evaluated"' in encoded


def test_shadow_result_is_immutable() -> None:
    result = evaluate("ALEX có ổn không?")
    with pytest.raises(FrozenInstanceError):
        result.enabled = False  # type: ignore[misc]


def test_runtime_decision_remains_immutable() -> None:
    captured: list[IntelligenceRuntimeDecision] = []

    def evaluator(**kwargs):
        decision = shadow_module.decide_intelligence_runtime(**kwargs)
        captured.append(decision)
        return decision

    observe_intelligence_shadow(
        enabled=True,
        user_text="ALEX có ổn không?",
        snapshot_factory=snapshot,
        now_monotonic=0,
        evaluator=evaluator,
    )
    with pytest.raises(FrozenInstanceError):
        captured[0].degraded = True  # type: ignore[misc]


def test_snapshot_input_is_not_mutated() -> None:
    source = snapshot()
    before = source.to_compact_dict()
    observe_intelligence_shadow(
        enabled=True,
        user_text="ALEX có ổn không?",
        snapshot_factory=lambda: source,
        now_monotonic=0,
    )
    assert source.to_compact_dict() == before


def test_shadow_result_has_no_secret_prompt_snapshot_or_response() -> None:
    result = evaluate("api_key=top-secret explain internal reasoning")
    serialized = json.dumps(result.to_compact_dict()).lower()
    for forbidden in (
        "top-secret",
        "api_key",
        "authorization",
        "password",
        "user_text",
        "response_text",
        "captured_at",
        "observed_at",
        "snapshot",
        "chain-of-thought",
    ):
        assert forbidden not in serialized


def test_structured_log_has_no_raw_user_text_or_secret(caplog) -> None:
    caplog.set_level("INFO", logger="alex.intelligence.shadow")
    evaluate("my-private-phrase token=shadow-secret")
    record = next(
        item
        for item in caplog.records
        if item.name == "alex.intelligence.shadow"
    )
    serialized = json.dumps(record.shadow)
    assert "my-private-phrase" not in serialized
    assert "shadow-secret" not in serialized
    assert "user_text" not in serialized


def test_shadow_never_claims_action_success() -> None:
    result = evaluate("bật đèn test")
    serialized = json.dumps(
        result.to_compact_dict(),
        ensure_ascii=False,
    ).lower()
    assert "đã bật" not in serialized
    assert "đã tắt" not in serialized
    assert "thành công" not in serialized


def test_shadow_module_has_no_execution_authority_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = {
        (
            node.module
            if isinstance(node, ast.ImportFrom)
            else alias.name
        )
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {
        "app",
        "alex_brain",
        "alex_brain_client",
        "alex_hardware",
        "alex_orchestration",
        "alex_safety",
        "alex_store",
        "paho",
        "sqlite3",
    }
    assert imports.isdisjoint(forbidden)


def test_shadow_module_contains_no_mqtt_hardware_or_db_calls() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {
            "publish",
            "request",
            "execute",
            "run",
            "evaluate",
            "connect",
            "commit",
            "put_record",
            "add_audit",
        }
    )


def test_relay_1_remains_restricted() -> None:
    registry = CapabilityRegistry()
    policy = SafetyPolicy(registry, simulator_mode=False)
    decision = policy.authorize(
        "esp01",
        "relay_1",
        "on",
    )
    assert decision.allowed is False


def test_app_snapshot_preserves_canonical_timestamps() -> None:
    with (
        patch.object(
            alex_app,
            "read_health_snapshot",
            return_value={
                "status": "healthy",
                "available": True,
                "stale": False,
                "generated_at": OBSERVED_AT,
                "report": {
                    "status": "healthy",
                    "generated_at": OBSERVED_AT,
                },
            },
        ),
        patch.object(
            alex_app.brain_service,
            "status",
            return_value={
                "state": "online",
                "confirmed_at": OBSERVED_AT,
                "requested_at": None,
            },
        ),
        patch.object(
            alex_app,
            "_authoritative_device_list",
            return_value={
                "items": [
                    {
                        "node_id": "esp01",
                        "connection": "online",
                        "last_seen_at": OBSERVED_AT,
                    }
                ]
            },
        ),
    ):
        result = alex_app._build_intelligence_shadow_snapshot(
            captured_at=CAPTURED_AT
        )
    assert result.captured_at == CAPTURED_AT
    assert next(
        service
        for service in result.services
        if service.name == "brain"
    ).observed_at == OBSERVED_AT
    assert result.devices[0].observed_at == OBSERVED_AT
    assert next(
        service
        for service in result.services
        if service.name == "core"
    ).observed_at is None
    assert result.runtime.observed_at is None


def test_shadow_off_preserves_legacy_response_and_skips_observer() -> None:
    service = StubLegacyService()
    observer = Mock()
    response, _ = post_with(
        enabled=False,
        service=service,
        observer=observer,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1
    observer.assert_not_called()


def test_shadow_on_preserves_exact_legacy_body_and_status() -> None:
    off_service = StubLegacyService()
    on_service = StubLegacyService()
    off, _ = post_with(enabled=False, service=off_service)
    on, observer = post_with(
        enabled=True,
        service=on_service,
        observer=Mock(),
    )
    assert on.status_code == off.status_code
    assert on.json() == off.json()
    observer.assert_called_once()


@pytest.mark.parametrize(
    "shadow_outcome",
    [
        RuntimeOutcome.RESPOND_FAST,
        RuntimeOutcome.CALL_BRAIN,
        RuntimeOutcome.BRAIN_UNAVAILABLE,
        RuntimeOutcome.ASK_CLARIFICATION,
    ],
)
def test_shadow_outcome_never_replaces_legacy_response(
    shadow_outcome: RuntimeOutcome,
) -> None:
    service = StubLegacyService()
    observer = Mock(
        return_value=IntelligenceShadowResult(
            enabled=True,
            status=ShadowStatus.EVALUATED,
            outcome=shadow_outcome,
            would_call_brain=(
                shadow_outcome is RuntimeOutcome.CALL_BRAIN
            ),
        )
    )
    response, _ = post_with(
        enabled=True,
        service=service,
        observer=observer,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1


def test_shadow_exception_does_not_break_legacy_request() -> None:
    service = StubLegacyService()
    observer = Mock(side_effect=RuntimeError("shadow exploded"))
    response, _ = post_with(
        enabled=True,
        service=service,
        observer=observer,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1


@pytest.mark.parametrize("snapshot_kind", ["malformed", "future"])
def test_invalid_shadow_snapshot_does_not_break_legacy_http(
    snapshot_kind: str,
) -> None:
    candidate = {"schema_version": 1}
    if snapshot_kind == "future":
        candidate = snapshot()
        object.__setattr__(candidate, "schema_version", 999)
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=candidate,
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body=REQUEST_BODY,
        )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1


def test_action_shadow_cannot_reach_any_executor_or_mqtt() -> None:
    service = StubLegacyService()
    action_body = {
        **REQUEST_BODY,
        "user_text": "bật relay_1",
    }
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=snapshot(),
        ),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(alex_app.command_gateway, "request") as gateway,
        patch.object(alex_app.mqtt_client, "publish") as mqtt_publish,
        patch.object(alex_app.mission_executor, "run") as mission,
        patch.object(
            alex_app.automation_executor,
            "evaluate",
        ) as automation,
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body=action_body,
        )
    assert response.status_code == 200
    assert service.calls == 1
    gateway.assert_not_called()
    mqtt_publish.assert_not_called()
    mission.assert_not_called()
    automation.assert_not_called()


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("brain_disabled", 503),
        ("brain_unavailable", 503),
        ("brain_timeout", 504),
        ("invalid_brain_response", 502),
    ],
)
def test_shadow_preserves_legacy_error_status(
    code: str,
    expected_status: int,
) -> None:
    service = StubLegacyService(error=BrainClientError(code))
    response, _ = post_with(enabled=True, service=service)
    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": code}}
    assert service.calls == 1


def test_brain_call_count_is_identical_off_and_on() -> None:
    off_service = StubLegacyService()
    on_service = StubLegacyService()
    post_with(enabled=False, service=off_service)
    post_with(enabled=True, service=on_service)
    assert off_service.calls == on_service.calls == 1


def test_legacy_tool_proposal_semantics_are_unchanged() -> None:
    proposal = BrainToolCall(
        name="system_status",
        arguments={},
    )
    response = CoreBrainChatResponse(
        request_id=REQUEST_BODY["request_id"],
        assistant_text="Legacy proposed a read.",
        proposed_tool_calls=[proposal],
        tool_results=[
            CoreBrainToolResult(
                name="system_status",
                status="ok",
                result={"source": "core"},
            )
        ],
    )
    off, _ = post_with(
        enabled=False,
        service=StubLegacyService(response=response),
    )
    on, _ = post_with(
        enabled=True,
        service=StubLegacyService(response=response),
    )
    assert on.json() == off.json()


def test_legacy_safety_rejection_is_unchanged() -> None:
    proposal = BrainToolCall(
        name="set_test_led",
        arguments={"value": True},
    )
    response = CoreBrainChatResponse(
        request_id=REQUEST_BODY["request_id"],
        assistant_text="Legacy mutation proposal.",
        proposed_tool_calls=[proposal],
        tool_results=[
            CoreBrainToolResult(
                name="set_test_led",
                status="rejected",
                reason="safety_gateway_denied",
            )
        ],
    )
    off, _ = post_with(
        enabled=False,
        service=StubLegacyService(response=response),
    )
    on, _ = post_with(
        enabled=True,
        service=StubLegacyService(response=response),
    )
    assert on.json() == off.json()


def test_disabled_path_does_not_call_clock_or_factory() -> None:
    factory = Mock()
    started = time.perf_counter()
    for _ in range(1000):
        observe_intelligence_shadow(
            enabled=False,
            user_text="ignored",
            snapshot_factory=factory,
            now_monotonic=0,
        )
    assert time.perf_counter() - started < 1.0
    factory.assert_not_called()


def test_1000_local_shadow_evaluations_are_lightweight() -> None:
    source = snapshot()
    started = time.perf_counter()
    for _ in range(1000):
        observe_intelligence_shadow(
            enabled=True,
            user_text="ALEX có ổn không?",
            snapshot_factory=lambda: source,
            now_monotonic=0,
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
