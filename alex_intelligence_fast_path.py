from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from alex_brain_resilience import (
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
)
from alex_intelligence import IntelligenceRoute
from alex_intelligence_runtime import (
    IntelligenceRuntimeDecision,
    RuntimeOutcome,
    RuntimeReason,
    decide_intelligence_runtime,
)
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    SystemKnowledgeSnapshot,
)
from alex_knowledge_query import KnowledgeQueryScope


FAST_PATH_ENV_NAME: Final = "ALEX_INTELLIGENCE_FAST_PATH_ENABLED"
FAST_PATH_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
FAST_PATH_ELIGIBLE_SCOPES: Final = (
    KnowledgeQueryScope.SYSTEM_STATUS,
    KnowledgeQueryScope.DEVICE_LIST,
    KnowledgeQueryScope.DEVICE_DETAIL,
)
FAST_PATH_SCOPE_TOOLS: Final = MappingProxyType(
    {
        KnowledgeQueryScope.SYSTEM_STATUS: ("system_status",),
        KnowledgeQueryScope.DEVICE_LIST: ("list_devices",),
        KnowledgeQueryScope.DEVICE_DETAIL: ("list_devices",),
    }
)
_LOGGER = logging.getLogger("alex.intelligence.fast_path")


class FastPathStatus(str, Enum):
    DISABLED = "disabled"
    HANDLED = "handled"
    DECLINED = "declined"
    FAST_PATH_ERROR = "fast_path_error"


class FastPathReason(str, Enum):
    FLAG_DISABLED = "flag_disabled"
    READ_ONLY_RESPONSE = "read_only_response"
    RUNTIME_DECLINED = "runtime_declined"
    INELIGIBLE_PLAN = "ineligible_plan"
    INELIGIBLE_ROUTE = "ineligible_route"
    INELIGIBLE_SCOPE = "ineligible_scope"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_FAST_RESPONSE = "invalid_fast_response"
    FAST_PATH_ERROR = "fast_path_error"


@dataclass(frozen=True, slots=True)
class IntelligenceFastPathResult:
    """Internal activation result; only handled read responses may be public."""

    enabled: bool
    status: FastPathStatus
    reason: FastPathReason
    outcome: RuntimeOutcome | None = None
    scope: KnowledgeQueryScope | None = None
    brain_skipped: bool = False
    assistant_text: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    decision: IntelligenceRuntimeDecision | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def handled(self) -> bool:
        return (
            self.status is FastPathStatus.HANDLED
            and self.brain_skipped
            and self.outcome is RuntimeOutcome.RESPOND_FAST
            and self.scope in FAST_PATH_ELIGIBLE_SCOPES
            and isinstance(self.assistant_text, str)
            and bool(self.assistant_text)
            and isinstance(
                self.decision,
                IntelligenceRuntimeDecision,
            )
        )

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status.value,
            "reason": self.reason.value,
            "outcome": (
                self.outcome.value if self.outcome is not None else None
            ),
            "scope": self.scope.value if self.scope is not None else None,
            "brain_skipped": self.brain_skipped,
        }


SnapshotFactory = Callable[[], SystemKnowledgeSnapshot]
RuntimeEvaluator = Callable[..., IntelligenceRuntimeDecision]


def intelligence_fast_path_enabled(
    environ: Mapping[str, str],
) -> bool:
    """Parse the independent opt-in flag; unknown values remain disabled."""

    value = environ.get(FAST_PATH_ENV_NAME, "")
    return isinstance(value, str) and value.strip().lower() in (
        FAST_PATH_TRUE_VALUES
    )


def evaluate_intelligence_fast_path(
    *,
    enabled: bool,
    user_text: str,
    snapshot_factory: SnapshotFactory,
    now_monotonic: float,
    circuit_state: BrainCircuitBreakerState | None = None,
    circuit_config: BrainCircuitBreakerConfig | None = None,
    evaluator: RuntimeEvaluator = decide_intelligence_runtime,
) -> IntelligenceFastPathResult:
    """Try one local read-only response and otherwise decline to legacy."""

    if not enabled:
        return IntelligenceFastPathResult(
            enabled=False,
            status=FastPathStatus.DISABLED,
            reason=FastPathReason.FLAG_DISABLED,
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
        result = _classify_decision(decision)
    except Exception:
        result = IntelligenceFastPathResult(
            enabled=True,
            status=FastPathStatus.FAST_PATH_ERROR,
            reason=FastPathReason.FAST_PATH_ERROR,
        )

    _emit_observation(result)
    return result


def _classify_decision(
    decision: IntelligenceRuntimeDecision,
) -> IntelligenceFastPathResult:
    if not isinstance(decision, IntelligenceRuntimeDecision):
        raise TypeError("invalid_fast_path_runtime_decision")

    scope = decision.trace.knowledge_scope
    common = {
        "enabled": True,
        "outcome": decision.outcome,
        "scope": scope,
        "decision": decision,
    }
    if decision.outcome is not RuntimeOutcome.RESPOND_FAST:
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.RUNTIME_DECLINED,
            **common,
        )
    if (
        decision.reason is not RuntimeReason.FAST_RESPONSE_HANDLED
        or len(decision.plan.steps) != 1
        or decision.plan.multi_intent
        or decision.plan.requires_clarification
        or decision.selected_step is None
    ):
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.INELIGIBLE_PLAN,
            **common,
        )
    step = decision.selected_step
    if (
        step.decision.route is not IntelligenceRoute.SYSTEM
        or decision.trace.route is not IntelligenceRoute.SYSTEM
        or not step.decision.matched
        or step.decision.allowed_tool_names
        != FAST_PATH_SCOPE_TOOLS.get(scope)
    ):
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.INELIGIBLE_ROUTE,
            **common,
        )
    if scope not in FAST_PATH_ELIGIBLE_SCOPES:
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.INELIGIBLE_SCOPE,
            **common,
        )
    fast_response = decision.fast_response
    if (
        decision.knowledge_schema_version != KNOWLEDGE_SCHEMA_VERSION
        or fast_response is None
        or fast_response.knowledge_schema_version
        != KNOWLEDGE_SCHEMA_VERSION
    ):
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.UNSUPPORTED_SCHEMA,
            **common,
        )
    if (
        not fast_response.handled
        or not decision.trace.fast_response_handled
        or not isinstance(decision.response_text, str)
        or not decision.response_text
        or decision.response_text != fast_response.text
    ):
        return IntelligenceFastPathResult(
            status=FastPathStatus.DECLINED,
            reason=FastPathReason.INVALID_FAST_RESPONSE,
            **common,
        )
    return IntelligenceFastPathResult(
        status=FastPathStatus.HANDLED,
        reason=FastPathReason.READ_ONLY_RESPONSE,
        brain_skipped=True,
        assistant_text=decision.response_text,
        **common,
    )


def _emit_observation(
    result: IntelligenceFastPathResult,
) -> None:
    fields = result.to_compact_dict()
    try:
        _LOGGER.info("intelligence_fast_path", extra={"fast_path": fields})
    except Exception:
        pass
