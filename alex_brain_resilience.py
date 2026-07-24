from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final


class BrainCircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BrainDegradedMode(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    PROBING = "probing"


class BrainFailureKind(str, Enum):
    TRANSIENT_TRANSPORT = "transient_transport"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    AUTH_FAILURE = "auth_failure"
    CONFIGURATION_ERROR = "configuration_error"
    BAD_REQUEST = "bad_request"
    CONTRACT_ERROR = "contract_error"
    UNKNOWN = "unknown"


class BrainFailureReason(str, Enum):
    CONNECTION_FAILED = "connection_failed"
    NETWORK_UNREACHABLE = "network_unreachable"
    BRAIN_TIMEOUT = "brain_timeout"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_NOT_CONFIGURED = "authentication_not_configured"
    INVALID_CREDENTIAL = "invalid_credential"
    CORE_BRAIN_NOT_CONFIGURED = "core_brain_not_configured"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE_CONTRACT = "invalid_response_contract"
    UNKNOWN_FAILURE = "unknown_failure"


class BrainRequestReason(str, Enum):
    CIRCUIT_CLOSED = "circuit_closed"
    CIRCUIT_OPEN = "circuit_open"
    CONFIGURATION_FAULT = "configuration_fault"
    PROBE_ALLOWED = "probe_allowed"
    PROBE_IN_PROGRESS = "probe_in_progress"
    MONOTONIC_TIME_MOVED_BACKWARDS = "monotonic_time_moved_backwards"


BREAKER_COUNTED_FAILURES: Final = frozenset(
    {
        BrainFailureKind.TRANSIENT_TRANSPORT,
        BrainFailureKind.TIMEOUT,
        BrainFailureKind.PROVIDER_UNAVAILABLE,
    }
)
BREAKER_IMMEDIATE_OPEN_FAILURES: Final = frozenset(
    {
        BrainFailureKind.AUTH_FAILURE,
        BrainFailureKind.CONFIGURATION_ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class BrainCircuitBreakerConfig:
    failure_threshold: int = 2
    recovery_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.failure_threshold, bool)
            or not isinstance(self.failure_threshold, int)
            or self.failure_threshold < 1
        ):
            raise ValueError("failure_threshold_must_be_positive_integer")
        timeout = self.recovery_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise ValueError("recovery_timeout_seconds_must_be_positive")
        object.__setattr__(self, "recovery_timeout_seconds", float(timeout))


@dataclass(frozen=True, slots=True)
class BrainFailure:
    kind: BrainFailureKind
    reason: BrainFailureReason

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BrainFailureKind):
            raise TypeError("invalid_brain_failure_kind")
        if not isinstance(self.reason, BrainFailureReason):
            raise TypeError("invalid_brain_failure_reason")


@dataclass(frozen=True, slots=True)
class BrainCircuitBreakerState:
    state: BrainCircuitState = BrainCircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at_monotonic: float | None = None
    last_failure_kind: BrainFailureKind | None = None
    last_failure_reason: BrainFailureReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, BrainCircuitState):
            raise TypeError("invalid_brain_circuit_state")
        if (
            isinstance(self.consecutive_failures, bool)
            or not isinstance(self.consecutive_failures, int)
            or self.consecutive_failures < 0
        ):
            raise ValueError("consecutive_failures_must_be_non_negative")
        if self.opened_at_monotonic is not None:
            _validate_monotonic(self.opened_at_monotonic)
        if self.state is BrainCircuitState.CLOSED:
            if self.opened_at_monotonic is not None:
                raise ValueError("closed_circuit_cannot_have_opened_at")
        elif self.opened_at_monotonic is None:
            raise ValueError("non_closed_circuit_requires_opened_at")
        if (
            self.last_failure_kind is not None
            and not isinstance(self.last_failure_kind, BrainFailureKind)
        ):
            raise TypeError("invalid_last_failure_kind")
        if (
            self.last_failure_reason is not None
            and not isinstance(self.last_failure_reason, BrainFailureReason)
        ):
            raise TypeError("invalid_last_failure_reason")

    @property
    def degraded_mode(self) -> BrainDegradedMode:
        if self.state is BrainCircuitState.CLOSED:
            return BrainDegradedMode.NORMAL
        if self.state is BrainCircuitState.HALF_OPEN:
            return BrainDegradedMode.PROBING
        return BrainDegradedMode.DEGRADED

    @property
    def degraded(self) -> bool:
        return self.degraded_mode is not BrainDegradedMode.NORMAL


@dataclass(frozen=True, slots=True)
class BrainRequestDecision:
    allowed: bool
    circuit_state: BrainCircuitState
    reason: BrainRequestReason
    degraded: bool
    probe: bool

    def __post_init__(self) -> None:
        if self.probe and (
            not self.allowed
            or self.circuit_state is not BrainCircuitState.HALF_OPEN
        ):
            raise ValueError("probe_must_be_allowed_in_half_open")


@dataclass(frozen=True, slots=True)
class BrainBeforeRequestResult:
    state: BrainCircuitBreakerState
    decision: BrainRequestDecision


def before_brain_request(
    state: BrainCircuitBreakerState,
    config: BrainCircuitBreakerConfig,
    *,
    now_monotonic: float,
) -> BrainBeforeRequestResult:
    """Return permission and the explicit next state without doing any I/O."""

    now = _validate_monotonic(now_monotonic)
    if state.state is BrainCircuitState.CLOSED:
        return _request_result(
            state,
            allowed=True,
            reason=BrainRequestReason.CIRCUIT_CLOSED,
        )
    if state.state is BrainCircuitState.HALF_OPEN:
        return _request_result(
            state,
            allowed=False,
            reason=BrainRequestReason.PROBE_IN_PROGRESS,
        )

    assert state.opened_at_monotonic is not None
    if now < state.opened_at_monotonic:
        return _request_result(
            state,
            allowed=False,
            reason=BrainRequestReason.MONOTONIC_TIME_MOVED_BACKWARDS,
        )
    elapsed = now - state.opened_at_monotonic
    if elapsed < config.recovery_timeout_seconds:
        reason = (
            BrainRequestReason.CONFIGURATION_FAULT
            if state.last_failure_kind in BREAKER_IMMEDIATE_OPEN_FAILURES
            else BrainRequestReason.CIRCUIT_OPEN
        )
        return _request_result(state, allowed=False, reason=reason)

    probing_state = replace(state, state=BrainCircuitState.HALF_OPEN)
    return _request_result(
        probing_state,
        allowed=True,
        reason=BrainRequestReason.PROBE_ALLOWED,
        probe=True,
    )


def record_brain_success(
    state: BrainCircuitBreakerState,
) -> BrainCircuitBreakerState:
    """Record only an actual Brain response; this never asserts action success."""

    if state.state is BrainCircuitState.OPEN:
        return state
    return BrainCircuitBreakerState()


def record_brain_failure(
    state: BrainCircuitBreakerState,
    config: BrainCircuitBreakerConfig,
    *,
    failure: BrainFailure,
    now_monotonic: float,
) -> BrainCircuitBreakerState:
    """Apply a classified, bounded failure without retaining raw error text."""

    now = _validate_monotonic(now_monotonic)
    if failure.kind in BREAKER_IMMEDIATE_OPEN_FAILURES:
        return _open_after_failure(state, failure, now)
    if failure.kind not in BREAKER_COUNTED_FAILURES:
        if state.state is not BrainCircuitState.CLOSED:
            return state
        return replace(
            state,
            last_failure_kind=failure.kind,
            last_failure_reason=failure.reason,
        )

    failures = state.consecutive_failures + 1
    if (
        state.state is BrainCircuitState.CLOSED
        and failures < config.failure_threshold
    ):
        return replace(
            state,
            consecutive_failures=failures,
            last_failure_kind=failure.kind,
            last_failure_reason=failure.reason,
        )
    return _open_after_failure(state, failure, now, failures=failures)


def classify_brain_failure(
    error_code: str,
    *,
    http_status: int | None = None,
) -> BrainFailure:
    """Map current bounded Core/Brain error codes without retaining raw input."""

    if error_code in {"brain_timeout", "provider_timeout"}:
        return BrainFailure(
            BrainFailureKind.TIMEOUT,
            (
                BrainFailureReason.PROVIDER_TIMEOUT
                if error_code == "provider_timeout"
                else BrainFailureReason.BRAIN_TIMEOUT
            ),
        )
    if error_code in {
        "provider_not_configured",
        "provider_unavailable",
        "ollama_unavailable",
    }:
        return BrainFailure(
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            (
                BrainFailureReason.PROVIDER_NOT_CONFIGURED
                if error_code == "provider_not_configured"
                else BrainFailureReason.PROVIDER_UNAVAILABLE
            ),
        )
    if error_code in {"authentication_required", "invalid_credential"}:
        return BrainFailure(
            BrainFailureKind.AUTH_FAILURE,
            (
                BrainFailureReason.AUTHENTICATION_REQUIRED
                if error_code == "authentication_required"
                else BrainFailureReason.INVALID_CREDENTIAL
            ),
        )
    if error_code in {
        "authentication_not_configured",
        "brain_not_configured",
    }:
        return BrainFailure(
            BrainFailureKind.CONFIGURATION_ERROR,
            (
                BrainFailureReason.AUTHENTICATION_NOT_CONFIGURED
                if error_code == "authentication_not_configured"
                else BrainFailureReason.CORE_BRAIN_NOT_CONFIGURED
            ),
        )
    if error_code == "invalid_request" or http_status == 422:
        return BrainFailure(
            BrainFailureKind.BAD_REQUEST,
            BrainFailureReason.INVALID_REQUEST,
        )
    if error_code in {
        "invalid_brain_response",
        "invalid_provider_response",
    }:
        return BrainFailure(
            BrainFailureKind.CONTRACT_ERROR,
            BrainFailureReason.INVALID_RESPONSE_CONTRACT,
        )
    if error_code in {
        "brain_unavailable",
        "connection_refused",
        "connection_reset",
        "network_unreachable",
    }:
        return BrainFailure(
            BrainFailureKind.TRANSIENT_TRANSPORT,
            (
                BrainFailureReason.NETWORK_UNREACHABLE
                if error_code == "network_unreachable"
                else BrainFailureReason.CONNECTION_FAILED
            ),
        )
    if http_status in {401, 403}:
        return BrainFailure(
            BrainFailureKind.AUTH_FAILURE,
            BrainFailureReason.INVALID_CREDENTIAL,
        )
    if http_status in {408, 504}:
        return BrainFailure(
            BrainFailureKind.TIMEOUT,
            BrainFailureReason.BRAIN_TIMEOUT,
        )
    if http_status == 503:
        return BrainFailure(
            BrainFailureKind.PROVIDER_UNAVAILABLE,
            BrainFailureReason.PROVIDER_UNAVAILABLE,
        )
    return BrainFailure(
        BrainFailureKind.UNKNOWN,
        BrainFailureReason.UNKNOWN_FAILURE,
    )


def compact_brain_circuit_state(
    state: BrainCircuitBreakerState,
) -> dict[str, Any]:
    """Return bounded telemetry data, separate from canonical Brain health."""

    return {
        "state": state.state.value,
        "mode": state.degraded_mode.value,
        "consecutive_failures": state.consecutive_failures,
        "opened_at_monotonic": state.opened_at_monotonic,
        "degraded": state.degraded,
        "last_failure_kind": (
            state.last_failure_kind.value
            if state.last_failure_kind is not None
            else None
        ),
        "last_failure_reason": (
            state.last_failure_reason.value
            if state.last_failure_reason is not None
            else None
        ),
    }


def _open_after_failure(
    state: BrainCircuitBreakerState,
    failure: BrainFailure,
    now: float,
    *,
    failures: int | None = None,
) -> BrainCircuitBreakerState:
    opened_at = now
    if state.opened_at_monotonic is not None:
        opened_at = max(state.opened_at_monotonic, now)
    return BrainCircuitBreakerState(
        state=BrainCircuitState.OPEN,
        consecutive_failures=(
            state.consecutive_failures + 1
            if failures is None
            else failures
        ),
        opened_at_monotonic=opened_at,
        last_failure_kind=failure.kind,
        last_failure_reason=failure.reason,
    )


def _request_result(
    state: BrainCircuitBreakerState,
    *,
    allowed: bool,
    reason: BrainRequestReason,
    probe: bool = False,
) -> BrainBeforeRequestResult:
    return BrainBeforeRequestResult(
        state=state,
        decision=BrainRequestDecision(
            allowed=allowed,
            circuit_state=state.state,
            reason=reason,
            degraded=state.degraded,
            probe=probe,
        ),
    )


def _validate_monotonic(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError("now_monotonic_must_be_non_negative_finite")
    return float(value)
