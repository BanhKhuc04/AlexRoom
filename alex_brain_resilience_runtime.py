from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from alex_brain_resilience import (
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainFailure,
    BrainFailureKind,
    BrainFailureReason,
    BrainRequestDecision,
    before_brain_request,
    classify_brain_failure,
    compact_brain_circuit_state,
    record_brain_failure,
    record_brain_success,
)


BRAIN_CIRCUIT_BREAKER_ENV_NAME: Final = (
    "ALEX_BRAIN_CIRCUIT_BREAKER_ENABLED"
)
BRAIN_CIRCUIT_BREAKER_TRUE_VALUES: Final = frozenset(
    {"1", "true", "yes", "on"}
)


@dataclass(frozen=True, slots=True)
class BrainRequestLease:
    """Opaque per-process lease; it contains no request or user data."""

    lease_id: int
    generation: int
    probe: bool


@dataclass(frozen=True, slots=True)
class LiveBrainRequestPermission:
    decision: BrainRequestDecision
    lease: BrainRequestLease | None

    def __post_init__(self) -> None:
        if self.decision.allowed != (self.lease is not None):
            raise ValueError("allowed_permission_requires_exactly_one_lease")
        if (
            self.lease is not None
            and self.decision.probe != self.lease.probe
        ):
            raise ValueError("probe_permission_must_match_lease")


Clock = Callable[[], float]


def brain_circuit_breaker_enabled(
    environ: Mapping[str, str],
) -> bool:
    """Parse the independent opt-in flag; unknown values remain disabled."""

    value = environ.get(BRAIN_CIRCUIT_BREAKER_ENV_NAME, "")
    return isinstance(value, str) and value.strip().lower() in (
        BRAIN_CIRCUIT_BREAKER_TRUE_VALUES
    )


class LiveBrainCircuitBreaker:
    """Thread-safe per-process owner around the pure breaker transitions."""

    def __init__(
        self,
        config: BrainCircuitBreakerConfig | None = None,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self._config = config or BrainCircuitBreakerConfig()
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BrainCircuitBreakerState()
        self._generation = 0
        self._next_lease_id = 1
        self._active_leases: dict[int, BrainRequestLease] = {}

    @property
    def config(self) -> BrainCircuitBreakerConfig:
        return self._config

    def before_request(self) -> LiveBrainRequestPermission:
        """Check/reserve under lock; callers perform network I/O afterwards."""

        now = self._clock()
        with self._lock:
            transition = before_brain_request(
                self._state,
                self._config,
                now_monotonic=now,
            )
            self._set_state(transition.state)
            lease = None
            if transition.decision.allowed:
                lease = BrainRequestLease(
                    lease_id=self._next_lease_id,
                    generation=self._generation,
                    probe=transition.decision.probe,
                )
                self._next_lease_id += 1
                self._active_leases[lease.lease_id] = lease
            return LiveBrainRequestPermission(
                decision=transition.decision,
                lease=lease,
            )

    def record_success(self, lease: BrainRequestLease) -> bool:
        """Apply only a current result; late results cannot close OPEN."""

        with self._lock:
            if not self._consume_current_lease(lease):
                return False
            self._set_state(record_brain_success(self._state))
            return True

    def record_failure(
        self,
        lease: BrainRequestLease,
        failure: BrainFailure,
    ) -> bool:
        now = self._clock()
        with self._lock:
            if not self._consume_current_lease(lease):
                return False
            self._set_state(
                record_brain_failure(
                    self._state,
                    self._config,
                    failure=failure,
                    now_monotonic=now,
                )
            )
            return True

    def record_failure_code(
        self,
        lease: BrainRequestLease,
        error_code: str,
        *,
        http_status: int | None = None,
    ) -> bool:
        failure = classify_brain_failure(
            error_code,
            http_status=http_status,
        )
        return self.record_failure(lease, failure)

    def abandon(self, lease: BrainRequestLease) -> bool:
        """Release an interrupted call; a reserved probe reopens safely."""

        now = self._clock()
        with self._lock:
            if not self._consume_current_lease(lease):
                return False
            if (
                lease.probe
                and self._state.state is BrainCircuitState.HALF_OPEN
            ):
                self._set_state(
                    record_brain_failure(
                        self._state,
                        self._config,
                        failure=BrainFailure(
                            BrainFailureKind.TRANSIENT_TRANSPORT,
                            BrainFailureReason.CONNECTION_FAILED,
                        ),
                        now_monotonic=now,
                    )
                )
            return True

    def state_snapshot(self) -> BrainCircuitBreakerState:
        with self._lock:
            return self._state

    def compact_snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = compact_brain_circuit_state(self._state)
            result.update(
                generation=self._generation,
                active_request_count=len(self._active_leases),
                probe_reserved=any(
                    lease.probe
                    for lease in self._active_leases.values()
                ),
                scope="per_process",
            )
            return result

    def reset(
        self,
        state: BrainCircuitBreakerState | None = None,
    ) -> None:
        """Reset lifecycle state; intended for process setup and tests."""

        replacement = state or BrainCircuitBreakerState()
        if not isinstance(replacement, BrainCircuitBreakerState):
            raise TypeError("invalid_brain_circuit_breaker_state")
        with self._lock:
            self._state = replacement
            self._generation += 1
            self._active_leases.clear()

    def _consume_current_lease(
        self,
        lease: BrainRequestLease,
    ) -> bool:
        if not isinstance(lease, BrainRequestLease):
            return False
        active = self._active_leases.pop(lease.lease_id, None)
        return (
            active == lease
            and lease.generation == self._generation
        )

    def _set_state(
        self,
        state: BrainCircuitBreakerState,
    ) -> None:
        previous_state = self._state.state
        self._state = state
        if state.state is not previous_state:
            self._generation += 1
            self._active_leases.clear()
