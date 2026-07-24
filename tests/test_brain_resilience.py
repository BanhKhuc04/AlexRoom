from __future__ import annotations

import ast
import json
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from alex_brain_resilience import (
    BREAKER_COUNTED_FAILURES,
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainDegradedMode,
    BrainFailure,
    BrainFailureKind,
    BrainFailureReason,
    BrainRequestReason,
    before_brain_request,
    classify_brain_failure,
    compact_brain_circuit_state,
    record_brain_failure,
    record_brain_success,
)
from alex_intelligence import IntelligenceRoute, route_intelligence
from alex_knowledge import build_system_knowledge_snapshot
from alex_safety import CapabilityRegistry, SafetyPolicy


CONFIG = BrainCircuitBreakerConfig(
    failure_threshold=2,
    recovery_timeout_seconds=20,
)
TRANSPORT_FAILURE = BrainFailure(
    BrainFailureKind.TRANSIENT_TRANSPORT,
    BrainFailureReason.CONNECTION_FAILED,
)
TIMEOUT_FAILURE = BrainFailure(
    BrainFailureKind.TIMEOUT,
    BrainFailureReason.BRAIN_TIMEOUT,
)
PROVIDER_FAILURE = BrainFailure(
    BrainFailureKind.PROVIDER_UNAVAILABLE,
    BrainFailureReason.PROVIDER_UNAVAILABLE,
)
AUTH_FAILURE = BrainFailure(
    BrainFailureKind.AUTH_FAILURE,
    BrainFailureReason.INVALID_CREDENTIAL,
)
BAD_REQUEST_FAILURE = BrainFailure(
    BrainFailureKind.BAD_REQUEST,
    BrainFailureReason.INVALID_REQUEST,
)


def open_state(
    *,
    opened_at: float = 10.0,
    failure: BrainFailure = TRANSPORT_FAILURE,
) -> BrainCircuitBreakerState:
    state = BrainCircuitBreakerState()
    state = record_brain_failure(
        state,
        CONFIG,
        failure=failure,
        now_monotonic=opened_at - 1,
    )
    return record_brain_failure(
        state,
        CONFIG,
        failure=failure,
        now_monotonic=opened_at,
    )


def test_initial_closed_allows_request() -> None:
    result = before_brain_request(
        BrainCircuitBreakerState(),
        CONFIG,
        now_monotonic=0,
    )
    assert result.state.state is BrainCircuitState.CLOSED
    assert result.decision.allowed is True
    assert result.decision.probe is False
    assert result.decision.degraded is False


def test_one_transient_failure_below_threshold_stays_closed() -> None:
    state = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=TRANSPORT_FAILURE,
        now_monotonic=1,
    )
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 1


def test_threshold_transient_failures_open_circuit() -> None:
    state = open_state()
    assert state.state is BrainCircuitState.OPEN
    assert state.consecutive_failures == 2
    assert state.opened_at_monotonic == 10


@pytest.mark.parametrize(
    ("failure", "expected_kind"),
    (
        (TIMEOUT_FAILURE, BrainFailureKind.TIMEOUT),
        (PROVIDER_FAILURE, BrainFailureKind.PROVIDER_UNAVAILABLE),
    ),
)
def test_timeout_and_provider_unavailable_count(
    failure: BrainFailure,
    expected_kind: BrainFailureKind,
) -> None:
    first = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=failure,
        now_monotonic=1,
    )
    second = record_brain_failure(
        first,
        CONFIG,
        failure=failure,
        now_monotonic=2,
    )
    assert expected_kind in BREAKER_COUNTED_FAILURES
    assert first.consecutive_failures == 1
    assert second.state is BrainCircuitState.OPEN


def test_auth_failure_opens_immediately_as_configuration_fault() -> None:
    state = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=AUTH_FAILURE,
        now_monotonic=4,
    )
    result = before_brain_request(state, CONFIG, now_monotonic=5)
    assert state.state is BrainCircuitState.OPEN
    assert state.consecutive_failures == 1
    assert result.decision.reason is BrainRequestReason.CONFIGURATION_FAULT
    assert result.decision.allowed is False


def test_bad_request_does_not_mark_brain_down() -> None:
    state = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=BAD_REQUEST_FAILURE,
        now_monotonic=1,
    )
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 0
    assert state.last_failure_kind is BrainFailureKind.BAD_REQUEST


def test_open_before_cooldown_denies_brain_request() -> None:
    result = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=29.999,
    )
    assert result.decision.allowed is False
    assert result.decision.reason is BrainRequestReason.CIRCUIT_OPEN
    assert result.state.state is BrainCircuitState.OPEN


def test_open_after_cooldown_allows_exactly_one_half_open_probe() -> None:
    first = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=30,
    )
    assert first.decision.allowed is True
    assert first.decision.probe is True
    assert first.state.state is BrainCircuitState.HALF_OPEN

    second = before_brain_request(
        first.state,
        CONFIG,
        now_monotonic=30,
    )
    assert second.decision.allowed is False
    assert second.decision.reason is BrainRequestReason.PROBE_IN_PROGRESS
    assert second.state == first.state


def test_half_open_successful_probe_closes_circuit() -> None:
    probing = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=30,
    ).state
    recovered = record_brain_success(probing)
    assert recovered == BrainCircuitBreakerState()


def test_half_open_failed_probe_reopens_and_resets_cooldown() -> None:
    probing = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=30,
    ).state
    reopened = record_brain_failure(
        probing,
        CONFIG,
        failure=TIMEOUT_FAILURE,
        now_monotonic=31,
    )
    assert reopened.state is BrainCircuitState.OPEN
    assert reopened.opened_at_monotonic == 31
    assert reopened.consecutive_failures == 3


def test_success_resets_consecutive_failures() -> None:
    failed_once = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=TRANSPORT_FAILURE,
        now_monotonic=1,
    )
    assert record_brain_success(failed_once) == BrainCircuitBreakerState()


def test_open_does_not_imply_core_or_router_unavailable() -> None:
    state = open_state()
    router_result = route_intelligence("Kiểm tra hệ thống ALEX.")
    assert state.state is BrainCircuitState.OPEN
    assert router_result.route is IntelligenceRoute.SYSTEM
    assert router_result.allowed_tool_names == ("system_status",)


def test_degraded_and_probing_modes_are_derived_from_circuit_state() -> None:
    opened = open_state()
    probing = before_brain_request(
        opened,
        CONFIG,
        now_monotonic=30,
    ).state
    assert opened.degraded is True
    assert opened.degraded_mode is BrainDegradedMode.DEGRADED
    assert probing.degraded is True
    assert probing.degraded_mode is BrainDegradedMode.PROBING


def test_raw_secret_and_user_text_cannot_be_stored_as_failure_reason() -> None:
    secret = "Authorization Bearer private-secret"
    user_text = "full private user request"
    for raw in (secret, user_text):
        classified = classify_brain_failure(raw)
        state = record_brain_failure(
            BrainCircuitBreakerState(),
            CONFIG,
            failure=classified,
            now_monotonic=1,
        )
        serialized = json.dumps(compact_brain_circuit_state(state))
        assert raw not in serialized
        assert classified.reason is BrainFailureReason.UNKNOWN_FAILURE

    with pytest.raises(TypeError):
        BrainCircuitBreakerState(
            last_failure_kind=BrainFailureKind.UNKNOWN,
            last_failure_reason=secret,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"failure_threshold": 0},
        {"failure_threshold": -1},
        {"failure_threshold": True},
        {"failure_threshold": 1.5},
        {"recovery_timeout_seconds": 0},
        {"recovery_timeout_seconds": -1},
        {"recovery_timeout_seconds": float("inf")},
        {"recovery_timeout_seconds": float("nan")},
        {"recovery_timeout_seconds": True},
    ),
)
def test_invalid_config_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        BrainCircuitBreakerConfig(**kwargs)  # type: ignore[arg-type]


def test_exact_cooldown_boundary_is_deterministic() -> None:
    before = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=29.999999,
    )
    at_boundary = before_brain_request(
        open_state(),
        CONFIG,
        now_monotonic=30,
    )
    assert before.decision.allowed is False
    assert at_boundary.decision.allowed is True
    assert at_boundary.decision.probe is True


def test_time_going_backwards_fails_safe() -> None:
    opened = open_state(opened_at=100)
    result = before_brain_request(
        opened,
        CONFIG,
        now_monotonic=99,
    )
    assert result.state == opened
    assert result.decision.allowed is False
    assert (
        result.decision.reason
        is BrainRequestReason.MONOTONIC_TIME_MOVED_BACKWARDS
    )

    probing = before_brain_request(
        opened,
        CONFIG,
        now_monotonic=120,
    ).state
    reopened = record_brain_failure(
        probing,
        CONFIG,
        failure=TIMEOUT_FAILURE,
        now_monotonic=90,
    )
    assert reopened.opened_at_monotonic == 100


def test_state_is_immutable() -> None:
    state = BrainCircuitBreakerState()
    with pytest.raises(FrozenInstanceError):
        state.consecutive_failures = 9  # type: ignore[misc]


def test_config_is_immutable() -> None:
    config = BrainCircuitBreakerConfig()
    with pytest.raises(FrozenInstanceError):
        config.failure_threshold = 9  # type: ignore[misc]


def test_transition_is_deterministic_for_identical_inputs() -> None:
    state = open_state()
    assert before_brain_request(
        state,
        CONFIG,
        now_monotonic=25,
    ) == before_brain_request(
        state,
        CONFIG,
        now_monotonic=25,
    )


def test_compact_representation_is_json_serializable_and_bounded() -> None:
    compact = compact_brain_circuit_state(open_state())
    encoded = json.dumps(compact)
    assert json.loads(encoded) == compact
    assert set(compact) == {
        "state",
        "mode",
        "consecutive_failures",
        "opened_at_monotonic",
        "degraded",
        "last_failure_kind",
        "last_failure_reason",
    }


def test_module_has_no_network_mqtt_ollama_or_hardware_dependencies() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "alex_brain_resilience.py"
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
        "threading",
        "multiprocessing",
        "subprocess",
        "sqlite3",
        "brain_service",
        "alex_hardware",
        "alex_orchestration",
        "alex_safety",
        "alex_store",
    }
    assert imports.isdisjoint(forbidden)


def test_relay_restrictions_remain_unchanged() -> None:
    policy = SafetyPolicy(CapabilityRegistry(), simulator_mode=False)
    for relay_id in range(1, 5):
        decision = policy.authorize(
            "esp01",
            f"relay_{relay_id}",
            "on",
        )
        assert decision.allowed is False
        assert decision.reason == "restricted_capability"


def test_circuit_state_does_not_mutate_knowledge_snapshot() -> None:
    snapshot = build_system_knowledge_snapshot(
        captured_at="2026-07-24T00:00:00+00:00",
        version="0.8.0",
        services={
            "core": {"status": "online"},
            "brain": {"status": "unknown"},
        },
    )
    before = snapshot.to_compact_dict()
    state = open_state()
    before_brain_request(state, CONFIG, now_monotonic=20)
    assert snapshot.to_compact_dict() == before
    brain = next(
        service for service in snapshot.services
        if service.name == "brain"
    )
    assert brain.status.value == "unknown"


def test_bad_caller_request_cannot_open_circuit_by_itself() -> None:
    state = BrainCircuitBreakerState()
    for tick in range(10):
        state = record_brain_failure(
            state,
            CONFIG,
            failure=BAD_REQUEST_FAILURE,
            now_monotonic=tick,
        )
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 0


def test_contract_error_does_not_open_circuit_by_itself() -> None:
    failure = BrainFailure(
        BrainFailureKind.CONTRACT_ERROR,
        BrainFailureReason.INVALID_RESPONSE_CONTRACT,
    )
    state = record_brain_failure(
        BrainCircuitBreakerState(),
        CONFIG,
        failure=failure,
        now_monotonic=1,
    )
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 0


def test_repeated_denied_calls_do_not_increment_failures() -> None:
    state = open_state()
    for tick in (11, 12, 13, 14):
        result = before_brain_request(
            state,
            CONFIG,
            now_monotonic=tick,
        )
        assert result.decision.allowed is False
        assert result.state == state
    assert state.consecutive_failures == 2


def test_contract_contains_no_fake_success_result_or_action_proposal() -> None:
    compact = compact_brain_circuit_state(open_state())
    assert "assistant_text" not in compact
    assert "tool_calls" not in compact
    assert "result" not in compact
    assert "action" not in compact
    assert "success" not in json.dumps(compact).lower()


@pytest.mark.parametrize(
    ("code", "status", "kind", "reason"),
    (
        (
            "brain_timeout",
            None,
            BrainFailureKind.TIMEOUT,
            BrainFailureReason.BRAIN_TIMEOUT,
        ),
        (
            "provider_timeout",
            504,
            BrainFailureKind.TIMEOUT,
            BrainFailureReason.PROVIDER_TIMEOUT,
        ),
        (
            "provider_not_configured",
            503,
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            BrainFailureReason.PROVIDER_NOT_CONFIGURED,
        ),
        (
            "invalid_credential",
            401,
            BrainFailureKind.AUTH_FAILURE,
            BrainFailureReason.INVALID_CREDENTIAL,
        ),
        (
            "invalid_request",
            422,
            BrainFailureKind.BAD_REQUEST,
            BrainFailureReason.INVALID_REQUEST,
        ),
        (
            "invalid_brain_response",
            502,
            BrainFailureKind.CONTRACT_ERROR,
            BrainFailureReason.INVALID_RESPONSE_CONTRACT,
        ),
    ),
)
def test_current_http_error_contract_is_classified_without_raw_details(
    code: str,
    status: int | None,
    kind: BrainFailureKind,
    reason: BrainFailureReason,
) -> None:
    assert classify_brain_failure(
        code,
        http_status=status,
    ) == BrainFailure(kind, reason)


def test_one_hundred_thousand_pure_checks_are_lightweight() -> None:
    state = BrainCircuitBreakerState()
    started = time.perf_counter()
    for tick in range(100_000):
        result = before_brain_request(
            state,
            CONFIG,
            now_monotonic=float(tick),
        )
        assert result.decision.allowed is True
    elapsed = time.perf_counter() - started
    assert elapsed < 30
