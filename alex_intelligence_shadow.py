from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from alex_brain_resilience import (
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
)
from alex_intelligence_runtime import (
    IntelligenceRuntimeDecision,
    RuntimeOutcome,
    RuntimeReason,
    decide_intelligence_runtime,
)
from alex_knowledge_contracts import SystemKnowledgeSnapshot


SHADOW_ENV_NAME: Final = "ALEX_INTELLIGENCE_SHADOW_ENABLED"
SHADOW_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
_LOGGER = logging.getLogger("alex.intelligence.shadow")


class ShadowStatus(str, Enum):
    DISABLED = "disabled"
    EVALUATED = "evaluated"
    SHADOW_ERROR = "shadow_error"


@dataclass(frozen=True, slots=True)
class IntelligenceShadowResult:
    """Bounded observation only; it has no execution or Brain-call method."""

    enabled: bool
    status: ShadowStatus
    outcome: RuntimeOutcome | None = None
    reason: RuntimeReason | None = None
    route: str | None = None
    certainty: str | None = None
    knowledge_scope: str | None = None
    fast_response_handled: bool = False
    would_call_brain: bool = False
    would_be_degraded: bool = False
    probe: bool = False

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status.value,
            "outcome": (
                self.outcome.value if self.outcome is not None else None
            ),
            "reason": (
                self.reason.value if self.reason is not None else None
            ),
            "route": self.route,
            "certainty": self.certainty,
            "knowledge_scope": self.knowledge_scope,
            "fast_response_handled": self.fast_response_handled,
            "would_call_brain": self.would_call_brain,
            "would_be_degraded": self.would_be_degraded,
            "probe": self.probe,
        }


ShadowObserver = Callable[[IntelligenceShadowResult], None]
SnapshotFactory = Callable[[], SystemKnowledgeSnapshot]
RuntimeEvaluator = Callable[..., IntelligenceRuntimeDecision]


def intelligence_shadow_enabled(
    environ: Mapping[str, str],
) -> bool:
    """Parse the opt-in flag strictly; every unrecognized value is disabled."""

    value = environ.get(SHADOW_ENV_NAME, "")
    return isinstance(value, str) and value.strip().lower() in SHADOW_TRUE_VALUES


def observe_intelligence_shadow(
    *,
    enabled: bool,
    user_text: str,
    snapshot_factory: SnapshotFactory,
    now_monotonic: float,
    circuit_state: BrainCircuitBreakerState | None = None,
    circuit_config: BrainCircuitBreakerConfig | None = None,
    observer: ShadowObserver | None = None,
    evaluator: RuntimeEvaluator = decide_intelligence_runtime,
) -> IntelligenceShadowResult:
    """Evaluate a local runtime shadow without changing the legacy decision."""

    if not enabled:
        return IntelligenceShadowResult(
            enabled=False,
            status=ShadowStatus.DISABLED,
        )

    try:
        snapshot = snapshot_factory()
        decision = evaluator(
            user_text=user_text,
            snapshot=snapshot,
            circuit_state=circuit_state or BrainCircuitBreakerState(),
            circuit_config=circuit_config or BrainCircuitBreakerConfig(),
            now_monotonic=now_monotonic,
        )
        result = _result_from_decision(decision)
    except Exception:
        result = IntelligenceShadowResult(
            enabled=True,
            status=ShadowStatus.SHADOW_ERROR,
        )

    _emit_observation(result, observer)
    return result


def observe_precomputed_intelligence_shadow(
    *,
    enabled: bool,
    decision: IntelligenceRuntimeDecision | None,
    observer: ShadowObserver | None = None,
) -> IntelligenceShadowResult:
    """Observe a decision already produced by the fast-path attempt."""

    if not enabled:
        return IntelligenceShadowResult(
            enabled=False,
            status=ShadowStatus.DISABLED,
        )
    try:
        result = _result_from_decision(decision)
    except Exception:
        result = IntelligenceShadowResult(
            enabled=True,
            status=ShadowStatus.SHADOW_ERROR,
        )
    _emit_observation(result, observer)
    return result


def _result_from_decision(
    decision: IntelligenceRuntimeDecision | None,
) -> IntelligenceShadowResult:
    if not isinstance(decision, IntelligenceRuntimeDecision):
        raise TypeError("invalid_shadow_runtime_decision")
    trace = decision.trace
    return IntelligenceShadowResult(
        enabled=True,
        status=ShadowStatus.EVALUATED,
        outcome=decision.outcome,
        reason=decision.reason,
        route=trace.route.value if trace.route is not None else None,
        certainty=(
            trace.certainty.value if trace.certainty is not None else None
        ),
        knowledge_scope=(
            trace.knowledge_scope.value
            if trace.knowledge_scope is not None
            else None
        ),
        fast_response_handled=trace.fast_response_handled,
        would_call_brain=decision.outcome is RuntimeOutcome.CALL_BRAIN,
        would_be_degraded=decision.degraded,
        probe=decision.probe,
    )


def _emit_observation(
    result: IntelligenceShadowResult,
    observer: ShadowObserver | None,
) -> None:
    fields = result.to_compact_dict()
    try:
        _LOGGER.info("intelligence_shadow", extra={"shadow": fields})
    except Exception:
        pass
    if observer is not None:
        try:
            observer(result)
        except Exception:
            pass
