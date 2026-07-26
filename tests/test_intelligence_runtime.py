from __future__ import annotations

import ast
import json
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import alex_intelligence_runtime as runtime_module
from alex_brain_resilience import (
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainFailureKind,
    BrainFailureReason,
)
from alex_fast_response import FastResponseReason
from alex_intelligence_runtime import (
    BRAIN_UNAVAILABLE_TEXT,
    DecisionTrace,
    IntelligenceRuntimeDecision,
    RuntimeOutcome,
    RuntimeReason,
    decide_intelligence_runtime,
)
from alex_knowledge import build_system_knowledge_snapshot
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeValue,
)
from alex_knowledge_query import (
    DeviceDetailQueryData,
    DeviceQueryData,
    KnowledgeQueryReason,
    KnowledgeQueryResult,
    KnowledgeQueryScope,
)
from alex_safety import CapabilityRegistry, SafetyPolicy


CAPTURED_AT = "2026-07-24T10:00:00+00:00"
OBSERVED_AT = "2026-07-24T09:59:00+00:00"
CONFIG = BrainCircuitBreakerConfig(
    failure_threshold=2,
    recovery_timeout_seconds=20,
)


def build_snapshot(
    *,
    overall_status: str = "healthy",
    core_status: str = "online",
    brain_status: str = "online",
    device_online: bool = True,
):
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        overall_status=overall_status,
        health_report={
            "status": "healthy",
            "available": True,
            "stale": False,
            "report": {
                "generated_at": OBSERVED_AT,
                "status": "healthy",
                "checks": {
                    "backup": {
                        "status": "healthy",
                        "available": True,
                        "stale": False,
                    },
                    "update": {"status": "unknown"},
                },
            },
        },
        services={
            "core": {
                "status": core_status,
                "available": True,
                "observed_at": OBSERVED_AT,
                "stale": False,
                "source": "core_runtime",
            },
            "brain": {
                "status": brain_status,
                "available": True,
                "observed_at": OBSERVED_AT,
                "stale": False,
                "source": "core_runtime",
            },
        },
        devices={
            "esp01": {
                "node_id": "esp01",
                "known": True,
                "available": True,
                "online": device_online,
                "connection": (
                    "online" if device_online else "offline"
                ),
                "observed_at": OBSERVED_AT,
                "verification_status": "basic_physical_validated",
                "hardware_verified": False,
                "source": "hardware_registry",
            }
        },
    )


def unknown_snapshot():
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
    )


def open_state(
    *,
    opened_at: float = 10.0,
) -> BrainCircuitBreakerState:
    return BrainCircuitBreakerState(
        state=BrainCircuitState.OPEN,
        consecutive_failures=2,
        opened_at_monotonic=opened_at,
        last_failure_kind=BrainFailureKind.TIMEOUT,
        last_failure_reason=BrainFailureReason.BRAIN_TIMEOUT,
    )


def half_open_state() -> BrainCircuitBreakerState:
    return BrainCircuitBreakerState(
        state=BrainCircuitState.HALF_OPEN,
        consecutive_failures=2,
        opened_at_monotonic=10,
        last_failure_kind=BrainFailureKind.TIMEOUT,
        last_failure_reason=BrainFailureReason.BRAIN_TIMEOUT,
    )


def decide(
    user_text: str,
    *,
    snapshot=None,
    circuit_state: BrainCircuitBreakerState | None = None,
    now: float = 0,
) -> IntelligenceRuntimeDecision:
    return decide_intelligence_runtime(
        user_text=user_text,
        snapshot=snapshot or build_snapshot(),
        circuit_state=circuit_state or BrainCircuitBreakerState(),
        circuit_config=CONFIG,
        now_monotonic=now,
    )


def test_system_status_with_healthy_knowledge_responds_fast() -> None:
    result = decide("ALEX có ổn không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.reason is RuntimeReason.FAST_RESPONSE_HANDLED
    assert result.brain_request_allowed is False
    assert result.brain_request is None
    assert result.response_text == (
        "ALEX đang hoạt động bình thường. Core và Brain đều online."
    )


def test_system_status_still_responds_fast_while_circuit_open() -> None:
    state = open_state()
    result = decide(
        "ALEX có ổn không?",
        circuit_state=state,
        now=11,
    )
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.degraded is True
    assert result.brain_request is None
    assert result.next_circuit_state == state


def test_device_detail_works_while_brain_open() -> None:
    result = decide(
        "ESP01 online không?",
        circuit_state=open_state(),
        now=11,
    )
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.trace.knowledge_scope is KnowledgeQueryScope.DEVICE_DETAIL
    assert "ESP01 online" in (result.response_text or "")
    assert result.brain_request_allowed is False


def test_clear_llm_reasoning_request_with_closed_circuit_calls_brain() -> None:
    result = decide("Giải thích tại sao hệ thống chậm")
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.brain_request_allowed is True
    assert result.response_text is None
    assert result.trace.brain_required is True


def test_clear_llm_reasoning_request_with_open_circuit_is_unavailable() -> None:
    result = decide(
        "Giải thích tại sao hệ thống chậm",
        circuit_state=open_state(),
        now=11,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.brain_request_allowed is False
    assert result.response_text == BRAIN_UNAVAILABLE_TEXT
    assert result.reason is RuntimeReason.BRAIN_CIRCUIT_OPEN


def test_open_response_does_not_fake_reasoning_answer() -> None:
    result = decide(
        "Giải thích tại sao hệ thống chậm",
        circuit_state=open_state(),
        now=11,
    )
    serialized = json.dumps(
        result.to_compact_dict(),
        ensure_ascii=False,
    ).lower()
    assert "vì hệ thống" not in serialized
    assert "reasoning" not in serialized
    assert result.fast_response is None


def test_clarification_has_priority_and_never_consults_brain_or_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("downstream stage must not run")

    monkeypatch.setattr(runtime_module, "query_knowledge", fail)
    monkeypatch.setattr(runtime_module, "before_brain_request", fail)
    result = decide("làm cái đó đi")
    assert result.outcome is RuntimeOutcome.ASK_CLARIFICATION
    assert result.brain_request is None
    assert result.trace.knowledge_scope is None


def test_turn_it_on_returns_specific_clarification() -> None:
    result = decide("bật nó lên")
    assert result.outcome is RuntimeOutcome.ASK_CLARIFICATION
    assert result.response_text == "Bạn muốn bật thiết bị nào?"
    assert result.brain_request_allowed is False


def test_empty_input_returns_safe_clarification() -> None:
    result = decide("")
    assert result.outcome is RuntimeOutcome.ASK_CLARIFICATION
    assert result.response_text == "Bạn muốn ALEX làm gì?"
    assert result.selected_step is None


def test_fast_path_never_consults_circuit_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("circuit must not run for handled fast path")

    monkeypatch.setattr(runtime_module, "before_brain_request", fail)
    result = decide("ALEX có ổn không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.brain_request is None


def test_test_led_action_with_closed_circuit_only_requests_brain() -> None:
    result = decide("bật đèn test")
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.brain_request_allowed is True
    assert result.fast_response is None
    assert result.response_text is None


def test_test_led_action_with_open_circuit_is_unavailable() -> None:
    result = decide(
        "bật đèn test",
        circuit_state=open_state(),
        now=11,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.response_text == BRAIN_UNAVAILABLE_TEXT
    assert "đã bật" not in result.response_text.lower()


@pytest.mark.parametrize(
    "user_text",
    (
        "đổi room mode",
        "chạy mission học tập",
        "chạy automation an toàn",
    ),
)
def test_other_action_paths_only_request_brain_without_execution(
    user_text: str,
) -> None:
    result = decide(user_text)
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.brain_request_allowed is True
    assert result.response_text is None
    assert result.fast_response is None


def test_relay_action_never_directly_executes_or_claims_success() -> None:
    closed = decide("bật relay_1")
    opened = decide(
        "bật relay_1",
        circuit_state=open_state(),
        now=11,
    )
    assert closed.outcome is RuntimeOutcome.CALL_BRAIN
    assert opened.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    for result in (closed, opened):
        compact = json.dumps(
            result.to_compact_dict(),
            ensure_ascii=False,
        ).lower()
        assert "đã bật" not in compact
        assert "thành công" not in compact
        assert "tool_calls" not in compact


def test_relay_restrictions_remain_unchanged() -> None:
    policy = SafetyPolicy(CapabilityRegistry(), simulator_mode=False)
    for relay_id in range(1, 5):
        result = policy.authorize(
            "esp01",
            f"relay_{relay_id}",
            "on",
        )
        assert result.allowed is False
        assert result.reason == "restricted_capability"


def test_unknown_knowledge_does_not_produce_fake_fast_response() -> None:
    result = decide(
        "ALEX có ổn không?",
        snapshot=unknown_snapshot(),
    )
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.fast_response is not None
    assert result.fast_response.handled is False
    assert (
        result.fast_response.reason
        is FastResponseReason.INSUFFICIENT_KNOWLEDGE
    )
    assert result.response_text is None


def stale_device_query() -> KnowledgeQueryResult:
    device = DeviceQueryData(
        device_id="esp01",
        known=KnowledgeValue.KNOWN_TRUE,
        available=KnowledgeValue.KNOWN_TRUE,
        online=KnowledgeValue.KNOWN_TRUE,
        observed_at=OBSERVED_AT,
        stale=KnowledgeValue.KNOWN_TRUE,
        hardware_verified=KnowledgeValue.KNOWN_FALSE,
        sources=(KnowledgeSource.CORE_RUNTIME,),
    )
    return KnowledgeQueryResult(
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        snapshot_captured_at=CAPTURED_AT,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        data=DeviceDetailQueryData(
            requested_device_id="esp01",
            found=True,
            device=device,
        ),
        sources=(KnowledgeSource.CORE_RUNTIME,),
        incomplete=False,
        reason=KnowledgeQueryReason.SELECTED_DEVICE_DETAIL,
    )


def test_stale_device_wording_is_preserved_through_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "query_knowledge",
        lambda *args, **kwargs: stale_device_query(),
    )
    result = decide("ESP01 online không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert "được đánh dấu là cũ" in (result.response_text or "")
    assert result.fast_response is not None
    assert "stale_data" in result.fast_response.warnings


def test_unknown_freshness_wording_is_preserved() -> None:
    result = decide("ESP01 online không?")
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert "chưa xác định được độ mới" in (result.response_text or "")
    assert result.fast_response is not None
    assert "freshness_unknown" in result.fast_response.warnings


def test_unsupported_knowledge_schema_fails_safe_without_brain() -> None:
    snapshot = build_snapshot()
    object.__setattr__(
        snapshot,
        "schema_version",
        KNOWLEDGE_SCHEMA_VERSION + 1,
    )
    result = decide(
        "Giải thích tại sao hệ thống chậm",
        snapshot=snapshot,
    )
    assert result.outcome is RuntimeOutcome.UNSUPPORTED
    assert (
        result.reason
        is RuntimeReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
    )
    assert result.brain_request is None
    assert result.brain_request_allowed is False


def test_unsupported_schema_is_rejected_before_knowledge_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = build_snapshot()
    object.__setattr__(
        snapshot,
        "schema_version",
        KNOWLEDGE_SCHEMA_VERSION + 1,
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("unsupported schema must not be queried")

    monkeypatch.setattr(runtime_module, "query_knowledge", fail)
    result = decide("ALEX có ổn không?", snapshot=snapshot)
    assert result.outcome is RuntimeOutcome.UNSUPPORTED
    assert result.fast_response is None


@pytest.mark.parametrize(
    "user_text",
    (
        "Giải thích tại sao hệ thống chậm",
        "Mấy giờ rồi?",
        "Thời tiết hôm nay thế nào?",
        "2 + 2",
    ),
)
def test_non_system_routes_do_not_query_or_dump_system_knowledge(
    user_text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("knowledge query must not run")

    monkeypatch.setattr(runtime_module, "query_knowledge", fail)
    result = decide(user_text)
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.trace.knowledge_scope is None
    assert "services" not in result.to_compact_dict()
    assert "devices" not in result.to_compact_dict()


def test_open_at_cooldown_boundary_reserves_half_open_probe() -> None:
    original = open_state()
    result = decide(
        "Kể cho tôi một câu chuyện",
        circuit_state=original,
        now=30,
    )
    assert result.outcome is RuntimeOutcome.CALL_BRAIN
    assert result.probe is True
    assert result.brain_request_allowed is True
    assert result.circuit_state is BrainCircuitState.HALF_OPEN
    assert result.next_circuit_state.state is BrainCircuitState.HALF_OPEN


def test_half_open_probe_already_reserved_is_denied() -> None:
    result = decide(
        "Kể cho tôi một câu chuyện",
        circuit_state=half_open_state(),
        now=30,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.probe is False
    assert (
        result.reason
        is RuntimeReason.BRAIN_PROBE_ALREADY_RESERVED
    )


def test_open_before_cooldown_is_unavailable() -> None:
    result = decide(
        "Kể cho tôi một câu chuyện",
        circuit_state=open_state(),
        now=29.999,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.probe is False
    assert result.circuit_state is BrainCircuitState.OPEN


def test_monotonic_time_going_backwards_denies_brain_safely() -> None:
    result = decide(
        "Kể cho tôi một câu chuyện",
        circuit_state=open_state(opened_at=100),
        now=99,
    )
    assert result.outcome is RuntimeOutcome.BRAIN_UNAVAILABLE
    assert result.reason is RuntimeReason.BRAIN_REQUEST_DENIED
    assert result.brain_request is not None
    assert (
        result.brain_request.reason.value
        == "monotonic_time_moved_backwards"
    )


def test_fast_path_does_not_consume_probe_at_cooldown_boundary() -> None:
    original = open_state()
    result = decide(
        "ALEX có ổn không?",
        circuit_state=original,
        now=30,
    )
    assert result.outcome is RuntimeOutcome.RESPOND_FAST
    assert result.next_circuit_state == original
    assert result.probe is False


def test_runtime_does_not_mutate_snapshot_or_breaker_input() -> None:
    snapshot = build_snapshot()
    state = open_state()
    snapshot_before = snapshot.to_compact_dict()
    state_before = state
    decide(
        "Kể cho tôi một câu chuyện",
        snapshot=snapshot,
        circuit_state=state,
        now=30,
    )
    assert snapshot.to_compact_dict() == snapshot_before
    assert state == state_before
    assert state.state is BrainCircuitState.OPEN


def test_result_and_trace_are_immutable() -> None:
    result = decide("ALEX có ổn không?")
    with pytest.raises(FrozenInstanceError):
        result.outcome = RuntimeOutcome.UNSUPPORTED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.trace.probe = True  # type: ignore[misc]


def test_result_is_deterministic() -> None:
    first = decide("ALEX có ổn không?")
    second = decide("ALEX có ổn không?")
    assert first == second
    assert first.to_compact_dict() == second.to_compact_dict()


def test_compact_result_is_json_serializable_and_excludes_raw_prompt() -> None:
    prompt = "Giải thích private-prompt-token"
    result = decide(prompt)
    encoded = json.dumps(
        result.to_compact_dict(),
        ensure_ascii=False,
    )
    assert json.loads(encoded) == result.to_compact_dict()
    assert prompt not in encoded
    assert "private-prompt-token" not in encoded


def test_decision_trace_contains_no_secret_or_hidden_reasoning() -> None:
    secret = "brain-api-key-secret"
    result = decide(f"Giải thích thiết kế {secret}")
    compact = result.trace.to_compact_dict()
    serialized = json.dumps(compact)
    assert secret not in serialized
    assert set(compact) == {
        "route",
        "certainty",
        "knowledge_scope",
        "fast_response",
        "fast_response_reason",
        "brain_required",
        "circuit_state",
        "probe",
        "step_count",
        "multi_intent",
    }
    assert all(
        word not in serialized.lower()
        for word in ("chain-of-thought", "hidden_reasoning", "analysis")
    )


def test_call_brain_trace_is_factual_and_bounded() -> None:
    result = decide("Kể cho tôi một câu chuyện")
    trace = result.trace.to_compact_dict()
    assert trace["route"] == "llm"
    assert trace["certainty"] == "exact"
    assert trace["knowledge_scope"] is None
    assert trace["fast_response"] == "not_attempted"
    assert trace["brain_required"] is True
    assert trace["circuit_state"] == "closed"
    assert trace["probe"] is False


def test_multi_intent_is_safe_unsupported_without_partial_response() -> None:
    result = decide(
        "trạng thái ALEX rồi liệt kê thiết bị",
    )
    assert result.outcome is RuntimeOutcome.UNSUPPORTED
    assert result.reason is RuntimeReason.UNSUPPORTED_MULTI_INTENT
    assert result.fast_response is None
    assert result.brain_request is None
    assert result.selected_step is None


def test_multi_intent_containing_action_never_claims_whole_plan_success() -> None:
    original = open_state()
    result = decide(
        "mấy giờ rồi, bật relay_1",
        circuit_state=original,
        now=30,
    )
    serialized = json.dumps(
        result.to_compact_dict(),
        ensure_ascii=False,
    ).lower()
    assert result.outcome is RuntimeOutcome.UNSUPPORTED
    assert result.next_circuit_state == original
    assert result.brain_request is None
    assert "đã thực hiện" not in serialized
    assert "thành công" not in serialized
    assert "respond_fast" not in serialized


def test_runtime_module_has_no_execution_or_external_io_dependencies() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "alex_intelligence_runtime.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden = {
        "socket",
        "urllib",
        "requests",
        "httpx",
        "paho",
        "paho.mqtt",
        "sqlite3",
        "threading",
        "subprocess",
        "brain_service",
        "alex_brain",
        "alex_brain_client",
        "alex_hardware",
        "alex_orchestration",
        "alex_safety",
        "alex_store",
    }
    assert imports.isdisjoint(forbidden)


def test_runtime_contract_has_no_execution_methods() -> None:
    assert not hasattr(IntelligenceRuntimeDecision, "execute")
    assert not hasattr(DecisionTrace, "execute")
    source = (
        Path(__file__).resolve().parents[1]
        / "alex_intelligence_runtime.py"
    ).read_text(encoding="utf-8")
    for forbidden_call in (
        "mqtt_client.publish",
        "CommandGateway(",
        ".request_ota(",
        ".put_record(",
        "urlopen(",
    ):
        assert forbidden_call not in source


def test_ten_thousand_local_read_only_decisions_are_lightweight() -> None:
    snapshot = build_snapshot()
    state = BrainCircuitBreakerState()
    started = time.perf_counter()
    for _ in range(10_000):
        result = decide_intelligence_runtime(
            user_text="ALEX có ổn không?",
            snapshot=snapshot,
            circuit_state=state,
            circuit_config=CONFIG,
            now_monotonic=0,
        )
        assert result.outcome is RuntimeOutcome.RESPOND_FAST
        assert result.brain_request is None
    elapsed = time.perf_counter() - started
    assert elapsed < 30
