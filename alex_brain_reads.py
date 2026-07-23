from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from alex_brain_tools import BrainToolCall


AuditWriter = Callable[[str, str, dict[str, object]], None]
ReadOperation = Callable[[], dict[str, object]]


@dataclass(frozen=True)
class ReadOutcome:
    status: Literal["ok", "error"]
    result: dict[str, object] | None
    reason: Literal["authoritative_read_failed"] | None


def execute_authoritative_read(
    *,
    request_id: str,
    call: BrainToolCall,
    operation: ReadOperation,
    audit: AuditWriter,
) -> ReadOutcome:
    audit(
        "read_execution",
        "info",
        {"request_id": request_id, "tool_name": call.name},
    )
    try:
        outcome = ReadOutcome(
            status="ok",
            result=operation(),
            reason=None,
        )
    except Exception:
        outcome = ReadOutcome(
            status="error",
            result=None,
            reason="authoritative_read_failed",
        )
    audit(
        "read_result",
        "info" if outcome.status == "ok" else "warning",
        {
            "request_id": request_id,
            "tool_name": call.name,
            "outcome": outcome.status,
        },
    )
    return outcome
