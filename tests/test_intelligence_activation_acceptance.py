from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException


os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_client import BrainClientError  # noqa: E402
from alex_brain_integration import CoreBrainChatResponse  # noqa: E402
from alex_brain_resilience import (  # noqa: E402
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainFailureKind,
    BrainFailureReason,
)
from alex_brain_resilience_runtime import (  # noqa: E402
    LiveBrainCircuitBreaker,
    brain_circuit_breaker_enabled,
)
from alex_brain_tools import BrainChatRequest  # noqa: E402
from alex_intelligence_fast_path import (  # noqa: E402
    intelligence_fast_path_enabled,
)
from alex_intelligence_shadow import (  # noqa: E402
    intelligence_shadow_enabled,
)
from alex_safety import CapabilityRegistry, SafetyPolicy  # noqa: E402
from test_intelligence_fast_path_integration import (  # noqa: E402
    knowledge_snapshot,
)


AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}
CLIENT = AsgiTestClient(alex_app.app)
CONFIG = BrainCircuitBreakerConfig(
    failure_threshold=2,
    recovery_timeout_seconds=20,
)
RESPONSE_KEYS = {
    "request_id",
    "assistant_text",
    "proposed_tool_calls",
    "tool_results",
}
SUCCESS_WORDING = (
    "đã bật",
    "đã tắt",
    "đã thực hiện thành công",
)


@dataclass(frozen=True, slots=True)
class FlagConfiguration:
    shadow: bool
    fast: bool
    breaker: bool

    @property
    def test_id(self) -> str:
        return (
            f"S{int(self.shadow)}-"
            f"F{int(self.fast)}-"
            f"B{int(self.breaker)}"
        )


@dataclass(frozen=True, slots=True)
class GoldenRequest:
    name: str
    text: str
    fast_eligible: bool
    action_like: bool = False


FLAG_MATRIX = tuple(
    FlagConfiguration(shadow, fast, breaker)
    for shadow in (False, True)
    for fast in (False, True)
    for breaker in (False, True)
)
GOLDEN_REQUESTS = (
    GoldenRequest("system_status", "ALEX có ổn không?", True),
    GoldenRequest("device_list", "liệt kê thiết bị", True),
    GoldenRequest("device_detail", "ESP01 online không?", True),
    GoldenRequest("unknown_device", "ESP99 online không?", False),
    GoldenRequest(
        "reasoning",
        "Giải thích tại sao hệ thống chậm",
        False,
    ),
    GoldenRequest("story", "Kể cho tôi một câu chuyện", False),
    GoldenRequest("ambiguous", "bật nó lên", False, True),
    GoldenRequest("test_led_on", "bật đèn test", False, True),
    GoldenRequest("test_led_off", "tắt đèn test", False, True),
    GoldenRequest("relay", "bật relay_1", False, True),
    GoldenRequest("room_mode", "chế độ ngủ", False, True),
    GoldenRequest(
        "mission",
        "chạy mission safe-study",
        False,
        True,
    ),
    GoldenRequest(
        "automation",
        "chạy automation safe-night",
        False,
        True,
    ),
    GoldenRequest(
        "multi_intent",
        "mấy giờ rồi, bật relay_1",
        False,
        True,
    ),
)


class ControlledClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class StubBrainService:
    def __init__(self, outcomes=None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls = 0
        self.calls_by_request_id: Counter[str] = Counter()

    def chat(
        self,
        request: BrainChatRequest,
    ) -> CoreBrainChatResponse:
        self.calls += 1
        self.calls_by_request_id[request.request_id] += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return CoreBrainChatResponse(
            request_id=request.request_id,
            assistant_text="Legacy Brain response.",
        )


class BlockingBrainService:
    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def chat(
        self,
        request: BrainChatRequest,
    ) -> CoreBrainChatResponse:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("acceptance_probe_release_timeout")
        return CoreBrainChatResponse(
            request_id=request.request_id,
            assistant_text="Probe completed.",
        )


class SoakBrainService(StubBrainService):
    def chat(
        self,
        request: BrainChatRequest,
    ) -> CoreBrainChatResponse:
        self.calls += 1
        self.calls_by_request_id[request.request_id] += 1
        if request.user_text == "inject Brain timeout":
            raise BrainClientError("brain_timeout")
        return CoreBrainChatResponse(
            request_id=request.request_id,
            assistant_text="Soak Brain response.",
        )


def open_state(
    *,
    opened_at: float = 100.0,
) -> BrainCircuitBreakerState:
    return BrainCircuitBreakerState(
        state=BrainCircuitState.OPEN,
        consecutive_failures=2,
        opened_at_monotonic=opened_at,
        last_failure_kind=BrainFailureKind.TIMEOUT,
        last_failure_reason=BrainFailureReason.BRAIN_TIMEOUT,
    )


def post_chat(
    text: str,
    *,
    flags: FlagConfiguration,
    owner: LiveBrainCircuitBreaker,
    service,
    request_id: str = "req-activation",
    snapshot=None,
):
    source = snapshot if snapshot is not None else knowledge_snapshot()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            flags.shadow,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            flags.fast,
        ),
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            flags.breaker,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=source,
        ),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(
            alex_app,
            "_observe_intelligence_shadow",
            wraps=alex_app._observe_intelligence_shadow,
        ) as shadow_observe,
        patch.object(
            alex_app,
            "observe_precomputed_intelligence_shadow",
            wraps=alex_app.observe_precomputed_intelligence_shadow,
        ) as shadow_precomputed,
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
            json_body={
                "request_id": request_id,
                "user_text": text,
            },
        )
    return {
        "response": response,
        "shadow_observe_calls": shadow_observe.call_count,
        "shadow_precomputed_calls": shadow_precomputed.call_count,
        "gateway_calls": gateway.call_count,
        "mqtt_calls": mqtt_publish.call_count,
        "mission_calls": mission.call_count,
        "automation_calls": automation.call_count,
    }


def assert_response_contract(response, request_id: str) -> dict[str, object]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["request_id"] == request_id
    assert isinstance(body["assistant_text"], str)
    assert isinstance(body["proposed_tool_calls"], list)
    assert isinstance(body["tool_results"], list)
    return body


def test_acceptance_matrix_has_all_eight_combinations_once() -> None:
    assert len(FLAG_MATRIX) == 8
    assert {
        (item.shadow, item.fast, item.breaker)
        for item in FLAG_MATRIX
    } == {
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (False, False, True),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    }


@pytest.mark.parametrize(
    "flags",
    FLAG_MATRIX,
    ids=lambda item: item.test_id,
)
@pytest.mark.parametrize(
    "golden",
    GOLDEN_REQUESTS,
    ids=lambda item: item.name,
)
def test_golden_request_set_across_all_flag_combinations(
    flags: FlagConfiguration,
    golden: GoldenRequest,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    result = post_chat(
        golden.text,
        flags=flags,
        owner=owner,
        service=service,
        request_id=f"req-{golden.name}",
    )
    body = assert_response_contract(
        result["response"],
        f"req-{golden.name}",
    )

    expected_brain_calls = int(
        not (flags.fast and golden.fast_eligible)
    )
    assert service.calls == expected_brain_calls
    assert service.calls <= 1
    if expected_brain_calls:
        assert body["assistant_text"] == "Legacy Brain response."
    else:
        assert body["assistant_text"] != "Legacy Brain response."
    assert body["proposed_tool_calls"] == []
    assert body["tool_results"] == []
    assert owner.state_snapshot() == BrainCircuitBreakerState()

    expected_shadow_calls = int(flags.shadow)
    assert (
        result["shadow_observe_calls"]
        + result["shadow_precomputed_calls"]
        == expected_shadow_calls
    )
    if flags.fast:
        assert result["shadow_observe_calls"] == 0
    else:
        assert result["shadow_precomputed_calls"] == 0

    assert result["gateway_calls"] == 0
    assert result["mqtt_calls"] == 0
    assert result["mission_calls"] == 0
    assert result["automation_calls"] == 0
    if golden.action_like:
        normalized = str(body["assistant_text"]).lower()
        assert not any(word in normalized for word in SUCCESS_WORDING)


@pytest.mark.parametrize(
    "flags",
    (
        FlagConfiguration(False, False, False),
        FlagConfiguration(True, False, False),
        FlagConfiguration(False, True, False),
        FlagConfiguration(False, False, True),
        FlagConfiguration(True, True, True),
    ),
    ids=lambda item: item.test_id,
)
def test_relay_is_never_locally_executed_or_granted(
    flags: FlagConfiguration,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    result = post_chat(
        "bật relay_1",
        flags=flags,
        owner=owner,
        service=service,
        request_id=f"req-relay-{flags.test_id}",
    )
    body = assert_response_contract(
        result["response"],
        f"req-relay-{flags.test_id}",
    )
    assert service.calls == 1
    assert result["gateway_calls"] == 0
    assert result["mqtt_calls"] == 0
    assert not any(
        word in str(body["assistant_text"]).lower()
        for word in SUCCESS_WORDING
    )

    decision = SafetyPolicy(
        CapabilityRegistry(),
        simulator_mode=False,
    ).authorize("esp01", "relay_1", "on")
    assert decision.allowed is False
    assert decision.reason == "restricted_capability"


def test_relay_while_open_is_degraded_without_brain_or_execution() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock(101))
    owner.reset(open_state())
    service = StubBrainService()
    result = post_chat(
        "bật relay_1",
        flags=FlagConfiguration(True, True, True),
        owner=owner,
        service=service,
        request_id="req-relay-open",
    )
    body = assert_response_contract(
        result["response"],
        "req-relay-open",
    )
    assert body["assistant_text"] == (
        "Brain hiện không khả dụng cho yêu cầu này."
    )
    assert service.calls == 0
    assert result["gateway_calls"] == 0
    assert result["mqtt_calls"] == 0
    assert owner.state_snapshot() == open_state()


def test_full_configuration_outage_fast_read_and_recovery_sequence() -> None:
    clock = ControlledClock()
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    service = StubBrainService(
        [
            BrainClientError("brain_timeout"),
            BrainClientError("brain_timeout"),
            CoreBrainChatResponse(
                request_id="req-probe",
                assistant_text="Probe recovered.",
            ),
        ]
    )
    flags = FlagConfiguration(True, True, True)

    first = post_chat(
        "Kể cho tôi một câu chuyện",
        flags=flags,
        owner=owner,
        service=service,
        request_id="req-timeout-1",
    )["response"]
    assert first.status_code == 504
    assert owner.state_snapshot().state is BrainCircuitState.CLOSED
    assert owner.state_snapshot().consecutive_failures == 1

    second = post_chat(
        "Giải thích tại sao hệ thống chậm",
        flags=flags,
        owner=owner,
        service=service,
        request_id="req-timeout-2",
    )["response"]
    assert second.status_code == 504
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert service.calls == 2

    denied = post_chat(
        "Kể cho tôi một câu chuyện",
        flags=flags,
        owner=owner,
        service=service,
        request_id="req-denied",
    )["response"]
    denied_body = assert_response_contract(denied, "req-denied")
    assert denied_body["assistant_text"] == (
        "Brain hiện không khả dụng cho yêu cầu này."
    )
    assert service.calls == 2

    open_snapshot = owner.compact_snapshot()
    for request_id, prompt in (
        ("req-open-system", "ALEX có ổn không?"),
        ("req-open-device", "ESP01 online không?"),
    ):
        fast = post_chat(
            prompt,
            flags=flags,
            owner=owner,
            service=service,
            request_id=request_id,
        )["response"]
        fast_body = assert_response_contract(fast, request_id)
        assert fast_body["assistant_text"] != (
            "Brain hiện không khả dụng cho yêu cầu này."
        )
    assert service.calls == 2
    assert owner.compact_snapshot() == open_snapshot

    clock.now = 120
    probe = post_chat(
        "Kể cho tôi một câu chuyện",
        flags=flags,
        owner=owner,
        service=service,
        request_id="req-probe",
    )["response"]
    probe_body = assert_response_contract(probe, "req-probe")
    assert probe_body["assistant_text"] == "Probe recovered."
    assert service.calls == 3
    assert owner.state_snapshot() == BrainCircuitBreakerState()

    normal = post_chat(
        "Kể cho tôi một câu chuyện",
        flags=flags,
        owner=owner,
        service=service,
        request_id="req-after-recovery",
    )["response"]
    assert_response_contract(normal, "req-after-recovery")
    assert service.calls == 4
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_all_flags_half_open_allows_one_probe_and_fast_reads() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = BlockingBrainService()
    flags = FlagConfiguration(True, True, True)
    probe_result: list[CoreBrainChatResponse] = []

    def call_direct(request_id: str, text: str) -> CoreBrainChatResponse:
        return alex_app.v1_brain_chat(
            BrainChatRequest(
                request_id=request_id,
                user_text=text,
            ),
            None,
        )

    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            flags.shadow,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            flags.fast,
        ),
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            flags.breaker,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        probe_thread = threading.Thread(
            target=lambda: probe_result.append(
                call_direct("req-concurrent-probe", "Kể chuyện")
            ),
        )
        probe_thread.start()
        assert service.started.wait(timeout=1)

        started = time.perf_counter()
        snapshot = owner.compact_snapshot()
        lock_check_elapsed = time.perf_counter() - started
        assert snapshot["state"] == "half_open"
        assert snapshot["probe_reserved"] is True
        assert lock_check_elapsed < 0.2

        with ThreadPoolExecutor(max_workers=8) as pool:
            denied = list(
                pool.map(
                    lambda index: call_direct(
                        f"req-denied-{index}",
                        "Giải thích hệ thống chậm",
                    ),
                    range(8),
                )
            )
        assert all(
            item.assistant_text
            == "Brain hiện không khả dụng cho yêu cầu này."
            for item in denied
        )
        assert service.calls == 1

        fast_system = call_direct(
            "req-concurrent-system",
            "ALEX có ổn không?",
        )
        fast_device = call_direct(
            "req-concurrent-device",
            "ESP01 online không?",
        )
        assert fast_system.assistant_text != (
            "Brain hiện không khả dụng cho yêu cầu này."
        )
        assert fast_device.assistant_text != (
            "Brain hiện không khả dụng cho yêu cầu này."
        )
        assert owner.state_snapshot().state is BrainCircuitState.HALF_OPEN
        assert service.calls == 1

        service.release.set()
        probe_thread.join(timeout=2)
        assert not probe_thread.is_alive()

    assert len(probe_result) == 1
    assert probe_result[0].assistant_text == "Probe completed."
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_snapshot_error_safely_falls_back_once() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            side_effect=RuntimeError("private snapshot failure"),
        ),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": "req-snapshot-error-direct",
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1


@pytest.mark.parametrize(
    "target",
    ["planner", "composer", "fast_boundary"],
)
def test_local_optimization_exception_safely_falls_back_once(
    target: str,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    patches = {
        "planner": patch(
            "alex_intelligence_runtime.plan_intelligence",
            side_effect=RuntimeError("private planner failure"),
        ),
        "composer": patch(
            "alex_intelligence_runtime.compose_fast_response",
            side_effect=RuntimeError("private composer failure"),
        ),
        "fast_boundary": patch.object(
            alex_app,
            "_evaluate_intelligence_fast_path",
            side_effect=RuntimeError("private fast-boundary failure"),
        ),
    }
    with patches[target]:
        result = post_chat(
            "ALEX có ổn không?",
            flags=FlagConfiguration(True, True, True),
            owner=owner,
            service=service,
            request_id=f"req-local-error-{target}",
        )
    body = assert_response_contract(
        result["response"],
        f"req-local-error-{target}",
    )
    assert body["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1
    assert owner.state_snapshot() == BrainCircuitBreakerState()


@pytest.mark.parametrize(
    ("error", "kind", "state", "failures"),
    (
        (
            BrainClientError("brain_unavailable"),
            BrainFailureKind.TRANSIENT_TRANSPORT,
            BrainCircuitState.CLOSED,
            1,
        ),
        (
            BrainClientError("brain_timeout"),
            BrainFailureKind.TIMEOUT,
            BrainCircuitState.CLOSED,
            1,
        ),
        (
            BrainClientError("provider_timeout"),
            BrainFailureKind.TIMEOUT,
            BrainCircuitState.CLOSED,
            1,
        ),
        (
            BrainClientError("provider_not_configured"),
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            BrainCircuitState.CLOSED,
            1,
        ),
        (
            BrainClientError("brain_unavailable", http_status=503),
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            BrainCircuitState.CLOSED,
            1,
        ),
        (
            BrainClientError("brain_unavailable", http_status=401),
            BrainFailureKind.AUTH_FAILURE,
            BrainCircuitState.OPEN,
            1,
        ),
        (
            BrainClientError("brain_unavailable", http_status=400),
            BrainFailureKind.BAD_REQUEST,
            BrainCircuitState.CLOSED,
            0,
        ),
        (
            BrainClientError("invalid_brain_response"),
            BrainFailureKind.CONTRACT_ERROR,
            BrainCircuitState.CLOSED,
            0,
        ),
    ),
    ids=(
        "transport",
        "timeout",
        "provider-timeout",
        "provider-not-configured",
        "provider-503",
        "auth-401",
        "caller-400",
        "invalid-response",
    ),
)
def test_error_injection_uses_canonical_breaker_classification(
    error: BrainClientError,
    kind: BrainFailureKind | None,
    state: BrainCircuitState,
    failures: int,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService([error])
    result = post_chat(
        "Kể cho tôi một câu chuyện",
        flags=FlagConfiguration(True, True, True),
        owner=owner,
        service=service,
        request_id="req-classification",
    )
    assert result["response"].status_code in {502, 503, 504}
    snapshot = owner.state_snapshot()
    assert snapshot.state is state
    assert snapshot.consecutive_failures == failures
    assert snapshot.last_failure_kind is kind
    assert service.calls == 1


def test_shadow_is_neutral_and_does_not_reserve_probe() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    before = owner.compact_snapshot()
    with (
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
    ):
        observed = alex_app._observe_intelligence_shadow(
            BrainChatRequest(
                request_id="req-shadow-neutral",
                user_text="Kể cho tôi một câu chuyện",
            )
        )
    assert observed.enabled is True
    assert owner.compact_snapshot() == before
    assert owner.compact_snapshot()["probe_reserved"] is False


def test_response_shadow_and_breaker_snapshots_are_private() -> None:
    secret = "acceptance-super-secret"
    raw_text = "private raw user history marker"
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock(101))
    owner.reset(open_state())
    service = StubBrainService()
    result = post_chat(
        raw_text,
        flags=FlagConfiguration(True, True, True),
        owner=owner,
        service=service,
        request_id="req-privacy",
    )
    public_body = assert_response_contract(
        result["response"],
        "req-privacy",
    )
    with (
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
    ):
        shadow = alex_app._observe_intelligence_shadow(
            BrainChatRequest(
                request_id="req-shadow-privacy",
                user_text=raw_text,
            )
        )
    serialized = json.dumps(
        {
            "public": public_body,
            "breaker": owner.compact_snapshot(),
            "shadow": shadow.to_compact_dict(),
        },
        ensure_ascii=False,
    )
    forbidden = (
        secret,
        raw_text,
        "ALEX_BRAIN_CLIENT_KEY",
        "Authorization",
        "MQTT_PASSWORD",
        "chain_of_thought",
        "raw_exception",
        "user_history",
    )
    assert all(item not in serialized for item in forbidden)


def test_individual_flag_rollback_and_fresh_process_reset() -> None:
    assert intelligence_shadow_enabled({}) is False
    assert intelligence_fast_path_enabled({}) is False
    assert brain_circuit_breaker_enabled({}) is False

    open_owner = LiveBrainCircuitBreaker(
        CONFIG,
        clock=ControlledClock(101),
    )
    open_owner.reset(open_state())
    service = StubBrainService()
    breaker_off = post_chat(
        "Kể chuyện",
        flags=FlagConfiguration(False, False, False),
        owner=open_owner,
        service=service,
        request_id="req-breaker-rollback",
    )
    body = assert_response_contract(
        breaker_off["response"],
        "req-breaker-rollback",
    )
    assert body["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1
    assert open_owner.state_snapshot() == open_state()

    fast_off_service = StubBrainService()
    fast_off = post_chat(
        "ALEX có ổn không?",
        flags=FlagConfiguration(False, False, True),
        owner=LiveBrainCircuitBreaker(
            CONFIG,
            clock=ControlledClock(),
        ),
        service=fast_off_service,
        request_id="req-fast-rollback",
    )
    assert_response_contract(
        fast_off["response"],
        "req-fast-rollback",
    )
    assert fast_off_service.calls == 1
    assert (
        fast_off["shadow_observe_calls"]
        + fast_off["shadow_precomputed_calls"]
        == 0
    )

    recreated = LiveBrainCircuitBreaker(
        CONFIG,
        clock=ControlledClock(),
    )
    assert recreated.state_snapshot() == BrainCircuitBreakerState()
    assert recreated.compact_snapshot()["active_request_count"] == 0


def test_flag_parsers_have_no_conflicting_default_or_true_values() -> None:
    true_values = ("1", "true", "TRUE", " yes ", "On")
    false_values = ("", "0", "false", "off", "enabled", "2")
    parsers = (
        (
            intelligence_shadow_enabled,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
        ),
        (
            intelligence_fast_path_enabled,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
        ),
        (
            brain_circuit_breaker_enabled,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
        ),
    )
    for parser, name in parsers:
        assert parser({}) is False
        assert all(parser({name: value}) for value in true_values)
        assert not any(parser({name: value}) for value in false_values)


def test_activation_layers_do_not_add_db_or_execution_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in (
            "alex_intelligence_shadow.py",
            "alex_intelligence_fast_path.py",
            "alex_brain_resilience_runtime.py",
        )
    )
    forbidden = (
        "sqlite3",
        "alex_store",
        "mqtt_client",
        ".publish(",
        "command_gateway",
        "gpio",
    )
    assert all(item not in sources for item in forbidden)


def test_deterministic_ten_thousand_request_soak() -> None:
    clock = ControlledClock()
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    service = SoakBrainService()
    shadow_observations = 0
    responses = 0
    http_errors = 0
    degraded = 0
    started = time.perf_counter()

    def observe_precomputed(**_kwargs):
        nonlocal shadow_observations
        shadow_observations += 1
        return None

    def invoke(request_id: str, text: str) -> None:
        nonlocal responses, http_errors, degraded
        payload = BrainChatRequest(
            request_id=request_id,
            user_text=text,
        )
        try:
            response = alex_app.v1_brain_chat(payload, None)
        except HTTPException as error:
            assert error.status_code in {503, 504}
            http_errors += 1
            responses += 1
            return
        body = response.model_dump(mode="json")
        assert set(body) == RESPONSE_KEYS
        if (
            body["assistant_text"]
            == "Brain hiện không khả dụng cho yêu cầu này."
        ):
            degraded += 1
        responses += 1

    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(
            alex_app,
            "observe_precomputed_intelligence_shadow",
            side_effect=observe_precomputed,
        ),
        patch.object(alex_app.command_gateway, "request") as gateway,
        patch.object(alex_app.mqtt_client, "publish") as mqtt_publish,
        patch.object(alex_app.mission_executor, "run") as mission,
        patch.object(
            alex_app.automation_executor,
            "evaluate",
        ) as automation,
    ):
        for cycle in range(100):
            if cycle:
                clock.now += 20
            sequence = (
                ("ALEX có ổn không?", 40),
                ("Kể cho tôi một câu chuyện", 20),
                ("bật nó lên", 10),
                ("bật đèn test", 10),
                ("ESP99 online không?", 10),
                ("inject Brain timeout", 10),
            )
            request_index = 0
            for text, count in sequence:
                for _ in range(count):
                    invoke(
                        f"soak-{cycle:03d}-{request_index:03d}",
                        text,
                    )
                    request_index += 1

    elapsed = time.perf_counter() - started
    assert responses == 10_000
    assert shadow_observations == 10_000
    assert http_errors == 200
    assert degraded == 800
    assert service.calls == 5_200
    assert max(service.calls_by_request_id.values()) == 1
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert owner.state_snapshot().consecutive_failures == 2
    assert owner.compact_snapshot()["active_request_count"] == 0
    assert gateway.call_count == 0
    assert mqtt_publish.call_count == 0
    assert mission.call_count == 0
    assert automation.call_count == 0
    print(f"activation_soak_elapsed_seconds={elapsed:.6f}")
