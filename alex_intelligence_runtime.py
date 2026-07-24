from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from alex_brain_resilience import (
    BrainBeforeRequestResult,
    BrainCircuitBreakerConfig,
    BrainCircuitBreakerState,
    BrainCircuitState,
    BrainRequestDecision,
    BrainRequestReason,
    before_brain_request,
    compact_brain_circuit_state,
)
from alex_fast_response import (
    FastResponseReason,
    FastResponseResult,
    compose_fast_response,
)
from alex_intelligence import IntelligenceRoute
from alex_intent_planner import (
    IntelligencePlan,
    IntentCertainty,
    IntentStep,
    plan_intelligence,
)
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    SystemKnowledgeSnapshot,
)
from alex_knowledge_query import (
    KnowledgeQueryScope,
    query_knowledge,
)


BRAIN_UNAVAILABLE_TEXT: Final = (
    "Brain hiện không khả dụng cho yêu cầu này."
)
UNSUPPORTED_SCHEMA_TEXT: Final = (
    "Phiên bản knowledge hiện chưa được runtime hỗ trợ."
)
UNSUPPORTED_MULTI_INTENT_TEXT: Final = (
    "Yêu cầu nhiều bước chưa được hỗ trợ trong pipeline này."
)


class RuntimeOutcome(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    RESPOND_FAST = "respond_fast"
    CALL_BRAIN = "call_brain"
    BRAIN_UNAVAILABLE = "brain_unavailable"
    UNSUPPORTED = "unsupported"


class RuntimeReason(str, Enum):
    CLARIFICATION_REQUIRED = "clarification_required"
    FAST_RESPONSE_HANDLED = "fast_response_handled"
    BRAIN_REQUEST_ALLOWED = "brain_request_allowed"
    BRAIN_CIRCUIT_OPEN = "brain_circuit_open"
    BRAIN_PROBE_ALREADY_RESERVED = "brain_probe_already_reserved"
    BRAIN_REQUEST_DENIED = "brain_request_denied"
    UNSUPPORTED_MULTI_INTENT = "unsupported_multi_intent"
    UNSUPPORTED_KNOWLEDGE_SCHEMA = "unsupported_knowledge_schema"


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    route: IntelligenceRoute | None
    certainty: IntentCertainty | None
    knowledge_scope: KnowledgeQueryScope | None
    fast_response_attempted: bool
    fast_response_handled: bool
    fast_response_reason: FastResponseReason | None
    brain_required: bool
    circuit_state: BrainCircuitState
    probe: bool
    step_count: int
    multi_intent: bool

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value if self.route is not None else None,
            "certainty": (
                self.certainty.value
                if self.certainty is not None
                else None
            ),
            "knowledge_scope": (
                self.knowledge_scope.value
                if self.knowledge_scope is not None
                else None
            ),
            "fast_response": (
                "handled"
                if self.fast_response_handled
                else (
                    "declined"
                    if self.fast_response_attempted
                    else "not_attempted"
                )
            ),
            "fast_response_reason": (
                self.fast_response_reason.value
                if self.fast_response_reason is not None
                else None
            ),
            "brain_required": self.brain_required,
            "circuit_state": self.circuit_state.value,
            "probe": self.probe,
            "step_count": self.step_count,
            "multi_intent": self.multi_intent,
        }


@dataclass(frozen=True, slots=True)
class IntelligenceRuntimeDecision:
    outcome: RuntimeOutcome
    reason: RuntimeReason
    plan: IntelligencePlan
    selected_step: IntentStep | None
    fast_response: FastResponseResult | None
    brain_request: BrainRequestDecision | None
    brain_request_allowed: bool
    degraded: bool
    probe: bool
    response_text: str | None
    circuit_state: BrainCircuitState
    next_circuit_state: BrainCircuitBreakerState
    knowledge_schema_version: int
    trace: DecisionTrace

    def __post_init__(self) -> None:
        if self.outcome is RuntimeOutcome.CALL_BRAIN:
            if not self.brain_request_allowed:
                raise ValueError("call_brain_requires_permission")
        elif self.brain_request_allowed:
            raise ValueError("brain_permission_requires_call_brain_outcome")
        if self.probe and self.outcome is not RuntimeOutcome.CALL_BRAIN:
            raise ValueError("probe_requires_call_brain_outcome")
        if self.outcome is RuntimeOutcome.RESPOND_FAST and (
            self.fast_response is None
            or not self.fast_response.handled
            or self.response_text is None
        ):
            raise ValueError("respond_fast_requires_handled_response")

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason.value,
            "response_text": self.response_text,
            "brain_request_allowed": self.brain_request_allowed,
            "degraded": self.degraded,
            "probe": self.probe,
            "circuit_state": self.circuit_state.value,
            "knowledge_schema_version": self.knowledge_schema_version,
            "plan": {
                "step_count": len(self.plan.steps),
                "multi_intent": self.plan.multi_intent,
                "requires_clarification": (
                    self.plan.requires_clarification
                ),
            },
            "selected_step_index": (
                self.selected_step.index
                if self.selected_step is not None
                else None
            ),
            "fast_response": (
                self.fast_response.to_compact_dict()
                if self.fast_response is not None
                else None
            ),
            "brain_request": (
                {
                    "allowed": self.brain_request.allowed,
                    "reason": self.brain_request.reason.value,
                    "probe": self.brain_request.probe,
                }
                if self.brain_request is not None
                else None
            ),
            "next_circuit_state": compact_brain_circuit_state(
                self.next_circuit_state
            ),
            "trace": self.trace.to_compact_dict(),
        }


def decide_intelligence_runtime(
    *,
    user_text: str,
    snapshot: SystemKnowledgeSnapshot,
    circuit_state: BrainCircuitBreakerState,
    circuit_config: BrainCircuitBreakerConfig,
    now_monotonic: float,
) -> IntelligenceRuntimeDecision:
    """Choose one runtime outcome without executing Brain, tools, or I/O."""

    plan = plan_intelligence(user_text)
    selected_step = plan.steps[0] if len(plan.steps) == 1 else None

    if plan.requires_clarification:
        return _result(
            outcome=RuntimeOutcome.ASK_CLARIFICATION,
            reason=RuntimeReason.CLARIFICATION_REQUIRED,
            plan=plan,
            selected_step=selected_step,
            circuit_state=circuit_state,
            snapshot=snapshot,
            response_text=plan.clarification_prompt,
        )
    if plan.multi_intent:
        return _result(
            outcome=RuntimeOutcome.UNSUPPORTED,
            reason=RuntimeReason.UNSUPPORTED_MULTI_INTENT,
            plan=plan,
            selected_step=None,
            circuit_state=circuit_state,
            snapshot=snapshot,
            response_text=UNSUPPORTED_MULTI_INTENT_TEXT,
        )
    if snapshot.schema_version != KNOWLEDGE_SCHEMA_VERSION:
        return _result(
            outcome=RuntimeOutcome.UNSUPPORTED,
            reason=RuntimeReason.UNSUPPORTED_KNOWLEDGE_SCHEMA,
            plan=plan,
            selected_step=selected_step,
            circuit_state=circuit_state,
            snapshot=snapshot,
            response_text=UNSUPPORTED_SCHEMA_TEXT,
        )

    assert selected_step is not None
    fast_response: FastResponseResult | None = None
    knowledge_scope: KnowledgeQueryScope | None = None
    if selected_step.decision.route is IntelligenceRoute.SYSTEM:
        knowledge = query_knowledge(
            snapshot,
            selected_step.decision,
            selected_step.original_text,
        )
        knowledge_scope = knowledge.scope
        fast_response = compose_fast_response(
            step=selected_step,
            knowledge=knowledge,
        )
        if fast_response.handled:
            return _result(
                outcome=RuntimeOutcome.RESPOND_FAST,
                reason=RuntimeReason.FAST_RESPONSE_HANDLED,
                plan=plan,
                selected_step=selected_step,
                circuit_state=circuit_state,
                snapshot=snapshot,
                response_text=fast_response.text,
                fast_response=fast_response,
                knowledge_scope=knowledge_scope,
            )

    permission = before_brain_request(
        circuit_state,
        circuit_config,
        now_monotonic=now_monotonic,
    )
    if permission.decision.allowed:
        return _result(
            outcome=RuntimeOutcome.CALL_BRAIN,
            reason=RuntimeReason.BRAIN_REQUEST_ALLOWED,
            plan=plan,
            selected_step=selected_step,
            circuit_state=permission.state,
            snapshot=snapshot,
            fast_response=fast_response,
            knowledge_scope=knowledge_scope,
            brain_permission=permission,
        )
    return _result(
        outcome=RuntimeOutcome.BRAIN_UNAVAILABLE,
        reason=_denied_reason(permission.decision.reason),
        plan=plan,
        selected_step=selected_step,
        circuit_state=permission.state,
        snapshot=snapshot,
        response_text=BRAIN_UNAVAILABLE_TEXT,
        fast_response=fast_response,
        knowledge_scope=knowledge_scope,
        brain_permission=permission,
    )


def _result(
    *,
    outcome: RuntimeOutcome,
    reason: RuntimeReason,
    plan: IntelligencePlan,
    selected_step: IntentStep | None,
    circuit_state: BrainCircuitBreakerState,
    snapshot: SystemKnowledgeSnapshot,
    response_text: str | None = None,
    fast_response: FastResponseResult | None = None,
    knowledge_scope: KnowledgeQueryScope | None = None,
    brain_permission: BrainBeforeRequestResult | None = None,
) -> IntelligenceRuntimeDecision:
    brain_request = (
        brain_permission.decision
        if brain_permission is not None
        else None
    )
    effective_state = (
        brain_permission.state
        if brain_permission is not None
        else circuit_state
    )
    brain_allowed = (
        outcome is RuntimeOutcome.CALL_BRAIN
        and brain_request is not None
        and brain_request.allowed
    )
    probe = bool(brain_request is not None and brain_request.probe)
    return IntelligenceRuntimeDecision(
        outcome=outcome,
        reason=reason,
        plan=plan,
        selected_step=selected_step,
        fast_response=fast_response,
        brain_request=brain_request,
        brain_request_allowed=brain_allowed,
        degraded=effective_state.degraded,
        probe=probe,
        response_text=response_text,
        circuit_state=effective_state.state,
        next_circuit_state=effective_state,
        knowledge_schema_version=snapshot.schema_version,
        trace=DecisionTrace(
            route=(
                selected_step.decision.route
                if selected_step is not None
                else None
            ),
            certainty=(
                selected_step.certainty
                if selected_step is not None
                else None
            ),
            knowledge_scope=knowledge_scope,
            fast_response_attempted=fast_response is not None,
            fast_response_handled=bool(
                fast_response is not None and fast_response.handled
            ),
            fast_response_reason=(
                fast_response.reason
                if fast_response is not None
                else None
            ),
            brain_required=outcome in {
                RuntimeOutcome.CALL_BRAIN,
                RuntimeOutcome.BRAIN_UNAVAILABLE,
            },
            circuit_state=effective_state.state,
            probe=probe,
            step_count=len(plan.steps),
            multi_intent=plan.multi_intent,
        ),
    )


def _denied_reason(reason: BrainRequestReason) -> RuntimeReason:
    if reason is BrainRequestReason.CIRCUIT_OPEN:
        return RuntimeReason.BRAIN_CIRCUIT_OPEN
    if reason is BrainRequestReason.PROBE_IN_PROGRESS:
        return RuntimeReason.BRAIN_PROBE_ALREADY_RESERVED
    return RuntimeReason.BRAIN_REQUEST_DENIED
