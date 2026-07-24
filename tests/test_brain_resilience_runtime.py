from __future__ import annotations

import ast
import json
import threading
import time
from pathlib import Path

import pytest

import alex_brain_resilience_runtime as runtime_module
from alex_brain_resilience import (
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainFailure,
    BrainFailureKind,
    BrainFailureReason,
)
from alex_brain_resilience_runtime import (
    LiveBrainCircuitBreaker,
    brain_circuit_breaker_enabled,
)


CONFIG = BrainCircuitBreakerConfig(
    failure_threshold=2,
    recovery_timeout_seconds=20,
)
MODULE_PATH = Path(runtime_module.__file__)


class ControlledClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def timeout_failure() -> BrainFailure:
    return BrainFailure(
        BrainFailureKind.TIMEOUT,
        BrainFailureReason.BRAIN_TIMEOUT,
    )


def transport_failure() -> BrainFailure:
    return BrainFailure(
        BrainFailureKind.TRANSIENT_TRANSPORT,
        BrainFailureReason.CONNECTION_FAILED,
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


def opened_owner(
    *,
    clock: ControlledClock | None = None,
) -> tuple[LiveBrainCircuitBreaker, ControlledClock]:
    source = clock or ControlledClock()
    owner = LiveBrainCircuitBreaker(CONFIG, clock=source)
    owner.reset(open_state())
    return owner, source


def test_flag_absent_is_off() -> None:
    assert brain_circuit_breaker_enabled({}) is False


@pytest.mark.parametrize(
    "value",
    ["false", "0", "no", "off", "", "enabled", "2"],
)
def test_false_and_invalid_flag_values_are_off(value: str) -> None:
    assert brain_circuit_breaker_enabled(
        {"ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED": value}
    ) is False


@pytest.mark.parametrize(
    "value",
    ["1", "true", "TRUE", " yes ", "On"],
)
def test_true_flag_values_are_on(value: str) -> None:
    assert brain_circuit_breaker_enabled(
        {"ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED": value}
    ) is True


def test_fresh_runtime_starts_closed_without_persistence() -> None:
    first = LiveBrainCircuitBreaker(CONFIG)
    second = LiveBrainCircuitBreaker(CONFIG)
    assert first.state_snapshot() == BrainCircuitBreakerState()
    assert second.state_snapshot() == BrainCircuitBreakerState()


def test_closed_allows_request_with_non_probe_lease() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.decision.allowed is True
    assert permission.decision.probe is False
    assert permission.lease is not None
    assert permission.lease.probe is False


def test_success_resets_closed_failure_counter() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    first = owner.before_request()
    assert first.lease is not None
    owner.record_failure(first.lease, timeout_failure())
    second = owner.before_request()
    assert second.lease is not None
    assert owner.record_success(second.lease) is True
    assert owner.state_snapshot() == BrainCircuitBreakerState()


def test_first_timeout_stays_closed() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.lease is not None
    owner.record_failure(permission.lease, timeout_failure())
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 1


def test_second_timeout_opens() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    for _ in range(2):
        permission = owner.before_request()
        assert permission.lease is not None
        owner.record_failure(permission.lease, timeout_failure())
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.OPEN
    assert state.consecutive_failures == 2


def test_open_before_cooldown_denies_without_lease() -> None:
    owner, clock = opened_owner()
    clock.now = 119.999
    permission = owner.before_request()
    assert permission.decision.allowed is False
    assert permission.lease is None


def test_repeated_open_denials_do_not_change_failure_count() -> None:
    owner, clock = opened_owner()
    before = owner.state_snapshot()
    for now in (101, 105, 110, 119):
        clock.now = now
        assert owner.before_request().decision.allowed is False
    assert owner.state_snapshot() == before


def test_exact_cooldown_boundary_reserves_probe() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    permission = owner.before_request()
    assert permission.decision.allowed is True
    assert permission.decision.probe is True
    assert permission.lease is not None
    assert permission.lease.probe is True
    assert owner.state_snapshot().state is BrainCircuitState.HALF_OPEN


def test_only_one_half_open_probe_is_reserved() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    first = owner.before_request()
    second = owner.before_request()
    assert first.decision.allowed is True
    assert first.decision.probe is True
    assert second.decision.allowed is False
    assert second.lease is None


def test_probe_success_closes() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    permission = owner.before_request()
    assert permission.lease is not None
    assert owner.record_success(permission.lease) is True
    assert owner.state_snapshot() == BrainCircuitBreakerState()


@pytest.mark.parametrize(
    "failure",
    [timeout_failure(), transport_failure()],
    ids=["timeout", "transport"],
)
def test_probe_counted_failure_reopens_and_resets_cooldown(
    failure: BrainFailure,
) -> None:
    owner, clock = opened_owner()
    clock.now = 120
    permission = owner.before_request()
    assert permission.lease is not None
    clock.now = 121
    owner.record_failure(permission.lease, failure)
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.OPEN
    assert state.opened_at_monotonic == 121


def test_abandoned_probe_reopens_instead_of_sticking() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    permission = owner.before_request()
    assert permission.lease is not None
    clock.now = 121
    assert owner.abandon(permission.lease) is True
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.OPEN
    assert state.opened_at_monotonic == 121


def test_contract_error_probe_reopens_and_resets_cooldown() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    permission = owner.before_request()
    assert permission.lease is not None
    clock.now = 121
    owner.record_failure_code(
        permission.lease,
        "invalid_brain_response",
        http_status=502,
    )
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.OPEN
    assert state.last_failure_kind is BrainFailureKind.CONTRACT_ERROR
    assert state.opened_at_monotonic == 121


@pytest.mark.parametrize(
    ("code", "status", "kind"),
    [
        ("brain_unavailable", None, BrainFailureKind.TRANSIENT_TRANSPORT),
        ("brain_timeout", None, BrainFailureKind.TIMEOUT),
        ("provider_timeout", 504, BrainFailureKind.TIMEOUT),
        (
            "provider_not_configured",
            503,
            BrainFailureKind.PROVIDER_UNAVAILABLE,
        ),
        ("brain_unavailable", 503, BrainFailureKind.PROVIDER_UNAVAILABLE),
    ],
)
def test_counted_failures_use_canonical_classification(
    code: str,
    status: int | None,
    kind: BrainFailureKind,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.lease is not None
    owner.record_failure_code(
        permission.lease,
        code,
        http_status=status,
    )
    assert owner.state_snapshot().last_failure_kind is kind


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_credential", 401),
        ("brain_unavailable", 401),
        ("brain_disabled", None),
        ("brain_not_configured", None),
        ("authentication_not_configured", None),
    ],
)
def test_auth_and_configuration_faults_open_immediately(
    code: str,
    status: int | None,
) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.lease is not None
    owner.record_failure_code(
        permission.lease,
        code,
        http_status=status,
    )
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_caller_4xx_does_not_open_or_increment(status: int) -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    for _ in range(4):
        permission = owner.before_request()
        assert permission.lease is not None
        owner.record_failure_code(
            permission.lease,
            "brain_unavailable",
            http_status=status,
        )
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 0
    assert state.last_failure_kind is BrainFailureKind.BAD_REQUEST


def test_contract_error_does_not_open_closed_circuit() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.lease is not None
    owner.record_failure_code(
        permission.lease,
        "invalid_brain_response",
        http_status=502,
    )
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.CLOSED
    assert state.consecutive_failures == 0


def test_simultaneous_failures_cannot_corrupt_counter() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    leases = []
    for _ in range(2):
        permission = owner.before_request()
        assert permission.lease is not None
        leases.append(permission.lease)
    barrier = threading.Barrier(3)
    results: list[bool] = []

    def fail(lease) -> None:
        barrier.wait()
        results.append(owner.record_failure(lease, timeout_failure()))

    threads = [
        threading.Thread(target=fail, args=(lease,))
        for lease in leases
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert sorted(results) == [True, True]
    state = owner.state_snapshot()
    assert state.state is BrainCircuitState.OPEN
    assert state.consecutive_failures == 2


def test_concurrent_half_open_permission_produces_one_probe() -> None:
    owner, clock = opened_owner()
    clock.now = 120
    barrier = threading.Barrier(9)
    permissions = []

    def reserve() -> None:
        barrier.wait()
        permissions.append(owner.before_request())

    threads = [threading.Thread(target=reserve) for _ in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    allowed = [
        item
        for item in permissions
        if item.decision.allowed
    ]
    assert len(allowed) == 1
    assert allowed[0].decision.probe is True


def test_late_success_after_open_is_ignored() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permissions = [owner.before_request() for _ in range(3)]
    leases = [item.lease for item in permissions]
    assert all(lease is not None for lease in leases)
    owner.record_failure(leases[0], timeout_failure())  # type: ignore[arg-type]
    owner.record_failure(leases[1], timeout_failure())  # type: ignore[arg-type]
    assert owner.state_snapshot().state is BrainCircuitState.OPEN
    assert owner.record_success(leases[2]) is False  # type: ignore[arg-type]
    assert owner.state_snapshot().state is BrainCircuitState.OPEN


def test_stale_failure_cannot_overwrite_newer_open_state() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permissions = [owner.before_request() for _ in range(3)]
    leases = [item.lease for item in permissions]
    owner.record_failure(leases[0], timeout_failure())  # type: ignore[arg-type]
    owner.record_failure(leases[1], timeout_failure())  # type: ignore[arg-type]
    opened = owner.state_snapshot()
    assert owner.record_failure(
        leases[2],  # type: ignore[arg-type]
        transport_failure(),
    ) is False
    assert owner.state_snapshot() == opened


def test_state_transitions_are_deterministic_with_controlled_clock() -> None:
    clock = ControlledClock(100)
    owner = LiveBrainCircuitBreaker(CONFIG, clock=clock)
    for now in (100, 101):
        clock.now = now
        permission = owner.before_request()
        assert permission.lease is not None
        owner.record_failure(permission.lease, timeout_failure())
    assert owner.state_snapshot().opened_at_monotonic == 101
    clock.now = 120.999
    assert owner.before_request().decision.allowed is False
    clock.now = 121
    assert owner.before_request().decision.probe is True


def test_reset_clears_active_leases_and_starts_closed() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    permission = owner.before_request()
    assert permission.lease is not None
    owner.reset()
    assert owner.state_snapshot() == BrainCircuitBreakerState()
    assert owner.record_success(permission.lease) is False
    assert owner.compact_snapshot()["active_request_count"] == 0


def test_compact_snapshot_is_sanitized() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    compact = owner.compact_snapshot()
    serialized = json.dumps(compact).lower()
    assert compact["scope"] == "per_process"
    for forbidden in (
        "api_key",
        "authorization",
        "password",
        "user_text",
        "exception",
        "lease_id",
        "request_id",
    ):
        assert forbidden not in serialized


def test_runtime_module_has_no_external_io_or_execution_authority() -> None:
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
    assert imports.isdisjoint(
        {
            "alex_hardware",
            "alex_orchestration",
            "alex_safety",
            "alex_store",
            "paho",
            "sqlite3",
            "urllib",
        }
    )


def test_runtime_module_has_no_mqtt_hardware_or_db_calls() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert attributes.isdisjoint(
        {
            "publish",
            "execute",
            "run",
            "connect",
            "commit",
            "put_record",
            "add_audit",
        }
    )


def test_one_hundred_thousand_closed_checks_are_lightweight() -> None:
    owner = LiveBrainCircuitBreaker(CONFIG, clock=ControlledClock())
    started = time.perf_counter()
    for _ in range(100_000):
        permission = owner.before_request()
        assert permission.lease is not None
        owner.record_success(permission.lease)
    assert time.perf_counter() - started < 30


def test_one_hundred_thousand_open_denials_are_lightweight() -> None:
    owner, clock = opened_owner()
    clock.now = 101
    started = time.perf_counter()
    for _ in range(100_000):
        assert owner.before_request().decision.allowed is False
    assert time.perf_counter() - started < 30
