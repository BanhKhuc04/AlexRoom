from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from alex_brain_tools import BrainToolCall


RoomMode = Literal["home", "away", "sleep", "study"]
RoomModeOutcomeReason = Literal["room_mode_execution_failed"]
AuditWriter = Callable[[str, str, dict[str, object]], None]
AuthoritativeRoomModeSetter = Callable[[RoomMode], dict[str, object]]


@dataclass(frozen=True)
class RoomModeAuditEvent:
    stage: str
    level: Literal["info", "warning"]
    details: dict[str, object]


@dataclass(frozen=True)
class RoomModeOutcome:
    status: Literal["ok", "error"]
    result: dict[str, object] | None
    reason: RoomModeOutcomeReason | None
    audit_events: tuple[RoomModeAuditEvent, ...]


class RoomModeExecutor(Protocol):
    def execute(self, mode: RoomMode) -> RoomModeOutcome: ...


class AuthoritativeRoomModeExecutor:
    """Call the existing Core logical-mode implementation and verify its result."""

    def __init__(self, setter: AuthoritativeRoomModeSetter) -> None:
        self._setter = setter

    def execute(self, mode: RoomMode) -> RoomModeOutcome:
        try:
            result = self._setter(mode)
        except Exception:
            return self._failed(mode)

        physical_actions = result.get("physical_actions")
        if (
            result.get("mode") != mode
            or result.get("logical_mode_updated") is not True
            or physical_actions != []
        ):
            return self._failed(mode)

        return RoomModeOutcome(
            status="ok",
            result=result,
            reason=None,
            audit_events=(
                RoomModeAuditEvent(
                    "room_mode_result",
                    "info",
                    {
                        "proposed_mode": mode,
                        "previous_mode": result.get("previous_mode"),
                        "new_mode": result["mode"],
                        "outcome": "logical_mode_updated",
                        "physical_action_count": 0,
                    },
                ),
            ),
        )

    @staticmethod
    def _failed(mode: RoomMode) -> RoomModeOutcome:
        return RoomModeOutcome(
            status="error",
            result=None,
            reason="room_mode_execution_failed",
            audit_events=(
                RoomModeAuditEvent(
                    "room_mode_result",
                    "warning",
                    {
                        "proposed_mode": mode,
                        "outcome": "room_mode_execution_failed",
                        "physical_action_count": 0,
                    },
                ),
            ),
        )


def execute_room_mode_proposal(
    *,
    request_id: str,
    call: BrainToolCall,
    executor: RoomModeExecutor | None,
    audit: AuditWriter,
) -> RoomModeOutcome:
    mode: RoomMode = call.arguments["mode"]
    audit(
        "room_mode_validated",
        "info",
        {
            "request_id": request_id,
            "tool_name": call.name,
            "proposed_mode": mode,
        },
    )
    if executor is None:
        outcome = AuthoritativeRoomModeExecutor._failed(mode)
    else:
        try:
            outcome = executor.execute(mode)
        except Exception:
            outcome = AuthoritativeRoomModeExecutor._failed(mode)

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
