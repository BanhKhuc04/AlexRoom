from __future__ import annotations

import json
import os
import threading
import time
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_client import (  # noqa: E402
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
)
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
)
from alex_brain_tools import BrainChatRequest  # noqa: E402
from alex_safety import CapabilityRegistry, SafetyPolicy  # noqa: E402
from test_intelligence_fast_path_integration import (  # noqa: E402
    knowledge_snapshot,
)


AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}
REQUEST_ID = "req-live-breaker"
CLIENT = AsgiTestClient(alex_app.app)
CONFIG = BrainCircuitBreakerConfig(
    failure_threshold=2,
    recovery_timeout_seconds=20,
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

    def chat(self, request: BrainChatRequest):
        self.calls += 1
        outcome = (
            self.outcomes.pop(0)
            if self.outcomes
            else CoreBrainChatResponse(
                request_id=request.request_id,
                assistant_text="Legacy Brain response.",
            )
        )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BlockingBrainService:
    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def chat(self, request: BrainChatRequest) -> CoreBrainChatResponse:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test_release_timeout")
        return CoreBrainChatResponse(
            request_id=request.request_id,
            assistant_text="Probe completed.",
        )


class SimulatedCancellation(BaseException):
    pass


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


def post(
    user_text: str,
    *,
    owner: LiveBrainCircuitBreaker,
    service,
    breaker_enabled: bool = True,
    fast_enabled: bool = False,
    shadow_enabled: bool = False,
):
    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            breaker_enabled,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            fast_enabled,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            shadow_enabled,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        return CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": user_text,
            },
        )


def test_breaker_flag_off_preserves_success_behavior() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    response = post(
        "Kể tôi một câu chuyện",
        owner=owner,
        service=service,
        breaker_enabled=False,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_breaker_flag_off_preserves_timeout_status_and_body() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService(
        [BrainClientError("brain_timeout")]
    )
    response = post(
        "Kể tôi một câu chuyện",
        owner=owner,
        service=service,
        breaker_enabled=False,
    )
    assert response.status_code == 504
    assert response.json() == {
        "detail": {"code": "brain_timeout"}
    }
    assert service.calls == 1
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_closed_success_calls_brain_once_and_stays_closed() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    response = post(
        "Kể tôi một câu chuyện",
        owner=owner,
        service=service,
    )
    assert response.status_code == 200
    assert service.calls == 1
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_two_timeouts_open_then_next_request_fast_fails() -> None:
    clock = ControlledClock()
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    service = StubBrainService(
        [
            BrainClientError("brain_timeout"),
            BrainClientError("brain_timeout"),
        ]
    )
    first = post("Kể chuyện", owner=owner, service=service)
    second = post("Kể chuyện", owner=owner, service=service)
    third = post("Kể chuyện", owner=owner, service=service)
    assert first.status_code == second.status_code == 504
    assert third.status_code == 200
    assert third.json()["assistant_text"] == (
        "Brain hiện không khả dụng cho yêu cầu này."
    )
    assert service.calls == 2
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


def test_open_degraded_response_preserves_schema_and_request_id() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock(101))
    owner.reset(open_state())
    response = post(
        "Kể tôi một câu chuyện",
        owner=owner,
        service=StubBrainService(),
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "request_id",
        "assistant_text",
        "proposed_tool_calls",
        "tool_results",
    }
    assert response.json()["request_id"] == REQUEST_ID
    assert response.json()["proposed_tool_calls"] == []
    assert response.json()["tool_results"] == []
    assert response.headers["content-type"].startswith("application/json")


def test_repeated_open_requests_do_not_call_or_mutate() -> None:
    clock = ControlledClock(101)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService()
    before = owner.state_snapshot()
    for _ in range(5):
        response = post(
            "Kể chuyện",
            owner=owner,
            service=service,
        )
        assert response.status_code == 200
    assert service.calls == 0
    assert owner.state_snapshot() == before


@pytest.mark.parametrize(
    "prompt",
    ["ALEX có ổn không?", "ESP01 online không?"],
)
def test_fast_read_still_works_while_open(prompt: str) -> None:
    clock = ControlledClock(101)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    before = owner.compact_snapshot()
    service = StubBrainService()
    response = post(
        prompt,
        owner=owner,
        service=service,
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"] != (
        "Brain hiện không khả dụng cho yêu cầu này."
    )
    assert service.calls == 0
    assert owner.compact_snapshot() == before


def test_fast_read_at_probe_boundary_does_not_reserve_probe() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService()
    response = post(
        "ALEX có ổn không?",
        owner=owner,
        service=service,
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert service.calls == 0
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert owner.compact_snapshot()["probe_reserved"] is False


def test_half_open_probe_success_closes_live_circuit() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService()
    response = post(
        "Kể chuyện",
        owner=owner,
        service=service,
    )
    assert response.status_code == 200
    assert service.calls == 1
    assert owner.state_snapshot() == BrainCircuitBreakerState()


@pytest.mark.parametrize(
    "error",
    [
        BrainClientError("brain_timeout"),
        BrainClientError("brain_unavailable"),
    ],
    ids=["timeout", "transport"],
)
def test_half_open_probe_failure_reopens(
    error: BrainClientError,
) -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService([error])
    response = post(
        "Kể chuyện",
        owner=owner,
        service=service,
    )
    assert response.status_code in {503, 504}
    assert service.calls == 1
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


def test_cancelled_probe_does_not_leave_half_open_stuck() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService([SimulatedCancellation()])
    payload = BrainChatRequest(
        request_id=REQUEST_ID,
        user_text="Kể chuyện",
    )
    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            False,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(alex_app, "core_brain_integration", service),
        pytest.raises(SimulatedCancellation),
    ):
        alex_app.v1_brain_chat(payload, None)
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert owner.compact_snapshot()["probe_reserved"] is False


@pytest.mark.parametrize(
    ("error", "expected_kind", "opens"),
    [
        (
            BrainClientError("brain_unavailable"),
            BrainFailureKind.TRANSIENT_TRANSPORT,
            False,
        ),
        (
            BrainClientError("brain_timeout"),
            BrainFailureKind.TIMEOUT,
            False,
        ),
        (
            BrainClientError(
                "brain_unavailable",
                http_status=503,
            ),
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            BrainClientError(
                "brain_unavailable",
                http_status=401,
            ),
            BrainFailureKind.AUTH_FAILURE,
            True,
        ),
        (
            BrainClientError("brain_not_configured"),
            BrainFailureKind.CONFIGURATION_ERROR,
            True,
        ),
        (
            BrainClientError(
                "brain_unavailable",
                http_status=400,
            ),
            BrainFailureKind.BAD_REQUEST,
            False,
        ),
        (
            BrainClientError("invalid_brain_response"),
            BrainFailureKind.CONTRACT_ERROR,
            False,
        ),
    ],
)
def test_real_error_mapping_updates_live_state(
    error: BrainClientError,
    expected_kind: BrainFailureKind,
    opens: bool,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService([error])
    response = post(
        "Kể chuyện",
        owner=owner,
        service=service,
    )
    assert response.status_code in {502, 503, 504}
    state = owner.state_snapshot()
    assert state.last_failure_kind is expected_kind
    assert (state.state is BrainCircuitState.OPEN) is opens


def test_http_401_retains_public_compatibility_but_opens_immediately() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService(
        [
            BrainClientError(
                "brain_unavailable",
                http_status=401,
            )
        ]
    )
    response = post(
        "Kể chuyện",
        owner=owner,
        service=service,
    )
    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "brain_unavailable"}
    }
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (400, "brain_unavailable"),
        (401, "brain_unavailable"),
        (503, "brain_unavailable"),
        (504, "brain_timeout"),
    ],
)
def test_real_core_client_preserves_bounded_code_and_http_status(
    status: int,
    expected_code: str,
) -> None:
    def opener(*_args, **_kwargs):
        raise HTTPError(
            "http://brain.test/v1/chat",
            status,
            "bounded upstream error",
            {},
            BytesIO(b"must-not-be-read"),
        )

    client = CoreBrainClient(
        CoreBrainConfig(
            enabled=True,
            url="http://brain.test",
            client_key="private-key",
        ),
        opener=opener,
    )
    with pytest.raises(BrainClientError) as raised:
        client.chat(
            BrainChatRequest(
                request_id=REQUEST_ID,
                user_text="Kể chuyện",
            )
        )
    assert raised.value.code == expected_code
    assert raised.value.http_status == status
    assert "must-not-be-read" not in str(raised.value)


def test_only_one_concurrent_half_open_request_reaches_brain() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = BlockingBrainService()
    payload = BrainChatRequest(
        request_id=REQUEST_ID,
        user_text="Kể chuyện",
    )
    result: list[CoreBrainChatResponse] = []

    def run_probe() -> None:
        result.append(
            alex_app._core_brain_chat_with_live_breaker(payload)
        )

    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        thread = threading.Thread(target=run_probe)
        thread.start()
        assert service.started.wait(timeout=1)
        denied = alex_app._core_brain_chat_with_live_breaker(payload)
        assert denied.assistant_text == (
            "Brain hiện không khả dụng cho yêu cầu này."
        )
        assert service.calls == 1
        service.release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert result[0].assistant_text == "Probe completed."
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_breaker_lock_is_not_held_during_brain_wait() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = BlockingBrainService()
    payload = BrainChatRequest(
        request_id=REQUEST_ID,
        user_text="Kể chuyện",
    )

    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        thread = threading.Thread(
            target=alex_app._core_brain_chat_with_live_breaker,
            args=(payload,),
        )
        thread.start()
        assert service.started.wait(timeout=1)
        started = time.perf_counter()
        snapshot = owner.compact_snapshot()
        elapsed = time.perf_counter() - started
        assert snapshot["active_request_count"] == 1
        assert elapsed < 0.2
        service.release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_breaker_infrastructure_failure_falls_back_to_legacy_once() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    service = StubBrainService()
    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(
            owner,
            "before_request",
            side_effect=RuntimeError("breaker bug"),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = alex_app._core_brain_chat_with_live_breaker(
            BrainChatRequest(
                request_id=REQUEST_ID,
                user_text="Kể chuyện",
            )
        )
    assert response.assistant_text == "Legacy Brain response."
    assert service.calls == 1


@pytest.mark.parametrize(
    "prompt",
    [
        "bật đèn test",
        "bật relay_1",
        "đổi room mode",
        "chạy mission học tập",
        "chạy automation an toàn",
    ],
)
def test_open_action_request_has_no_bypass_or_fake_success(
    prompt: str,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock(101))
    owner.reset(open_state())
    service = StubBrainService()
    with (
        patch.object(
            alex_app,
            "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(alex_app, "brain_circuit_breaker", owner),
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
            json_body={
                "request_id": REQUEST_ID,
                "user_text": prompt,
            },
        )
    text = response.json()["assistant_text"].lower()
    assert text == "brain hiện không khả dụng cho yêu cầu này."
    assert "đã bật" not in text
    assert "thành công" not in text
    assert service.calls == 0
    gateway.assert_not_called()
    mqtt_publish.assert_not_called()
    mission.assert_not_called()
    automation.assert_not_called()


def test_relay_safety_remains_restricted() -> None:
    policy = SafetyPolicy(CapabilityRegistry(), simulator_mode=False)
    decision = policy.authorize("esp01", "relay_1", "on")
    assert decision.allowed is False
    assert decision.reason == "restricted_capability"


def test_shadow_observation_does_not_mutate_or_reserve_live_breaker() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    before = owner.compact_snapshot()
    payload = BrainChatRequest(
        request_id=REQUEST_ID,
        user_text="Giải thích vì sao ALEX chậm",
    )
    with (
        patch.object(alex_app, "brain_circuit_breaker", owner),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
    ):
        alex_app._observe_intelligence_shadow(payload)
    assert owner.compact_snapshot() == before
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


def test_shadow_fast_breaker_flags_are_deterministic() -> None:
    clock = ControlledClock(120)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    owner.reset(open_state())
    service = StubBrainService()
    response = post(
        "ALEX có ổn không?",
        owner=owner,
        service=service,
        breaker_enabled=True,
        fast_enabled=True,
        shadow_enabled=True,
    )
    assert response.status_code == 200
    assert service.calls == 0
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert owner.compact_snapshot()["probe_reserved"] is False


def test_degraded_response_and_snapshot_do_not_leak_private_data() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock(101))
    owner.reset(open_state())
    response = post(
        "Kể chuyện với secret-token",
        owner=owner,
        service=StubBrainService(),
    )
    serialized = (
        response.text
        + json.dumps(owner.compact_snapshot())
    ).lower()
    for forbidden in (
        "secret-token",
        "authorization",
        "api_key",
        "password",
        "raw_exception",
        "chain-of-thought",
    ):
        assert forbidden not in serialized
