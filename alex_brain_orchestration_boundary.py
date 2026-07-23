from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from alex_brain_automations import AutomationOutcome
from alex_brain_missions import MissionOutcome
from alex_brain_tools import BrainToolCall


AuditWriter = Callable[[str, str, dict[str, object]], None]
StoredOrchestrationOutcome = MissionOutcome | AutomationOutcome


class StoredOrchestrationExecutor(Protocol):
    def execute(
        self,
        record_id: str,
    ) -> StoredOrchestrationOutcome: ...


def execute_stored_orchestration(
    *,
    request_id: str,
    call: BrainToolCall,
    executor: StoredOrchestrationExecutor | None,
    record_type: Literal["mission", "automation"],
    audit: AuditWriter,
) -> StoredOrchestrationOutcome | None:
    """Invoke a Core-owned stored-record adapter and emit bounded audit metadata."""

    record_id = str(call.arguments[f"{record_type}_id"])
    failure_reason = f"{record_type}_execution_failed"
    audit(
        f"{record_type}_proposal_validated",
        "info",
        {
            "request_id": request_id,
            "tool_name": call.name,
            f"{record_type}_id": record_id,
        },
    )
    if executor is None:
        audit(
            f"{record_type}_execution_outcome",
            "warning",
            {
                "request_id": request_id,
                "tool_name": call.name,
                f"{record_type}_id": record_id,
                "outcome": "failed",
                "failure_category": failure_reason,
            },
        )
        return None

    try:
        outcome = executor.execute(record_id)
    except Exception:
        audit(
            f"{record_type}_execution_outcome",
            "warning",
            {
                "request_id": request_id,
                "tool_name": call.name,
                f"{record_type}_id": record_id,
                "outcome": "failed",
                "failure_category": failure_reason,
            },
        )
        return None

    for event in outcome.audit_events:
        audit(
            event.stage,
            event.level,
            {
                "request_id": request_id,
                "tool_name": call.name,
                **event.details,
            },
        )
    return outcome
