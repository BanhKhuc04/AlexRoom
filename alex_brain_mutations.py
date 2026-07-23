from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Mapping

from alex_safety import CommandGateway, GatewayExecutionError


SET_TEST_LED_CORE_MAPPING: Final[Mapping[str, str]] = MappingProxyType(
    {
        "node_id": "esp01",
        "capability": "test_led",
        "action": "set",
    }
)

MutationOutcomeStatus = Literal["rejected", "pending", "confirmed", "failed"]
MutationOutcomeReason = Literal[
    "safety_gateway_denied",
    "device_unavailable",
    "command_not_created",
    "command_lifecycle_failed",
]


@dataclass(frozen=True)
class MutationOutcome:
    status: MutationOutcomeStatus
    result: dict[str, object]
    reason: MutationOutcomeReason | None
    audit: dict[str, object]


class CommandGatewaySetTestLedExecutor:
    """Fixed C5 mapping into the existing authoritative command gateway."""

    _COMMAND_FIELDS: Final[tuple[str, ...]] = (
        "command_id",
        "node_id",
        "target",
        "action",
        "desired_state",
        "reported_state",
        "phase",
        "source",
        "origin",
        "created_at",
        "requested_at",
        "sent_at",
        "acknowledged_at",
        "confirmed_at",
        "updated_at",
        "retry_count",
        "failure_reason",
        "ack_status",
    )

    def __init__(self, gateway: CommandGateway) -> None:
        self._gateway = gateway

    def execute(self, value: bool) -> MutationOutcome:
        try:
            gateway_result = self._gateway.request(
                node_id=SET_TEST_LED_CORE_MAPPING["node_id"],
                capability_id=SET_TEST_LED_CORE_MAPPING["capability"],
                action=SET_TEST_LED_CORE_MAPPING["action"],
                payload={"value": value},
                origin="brain",
            )
        except GatewayExecutionError as error:
            safe_decision = self._safe_decision(error.decision.as_dict())
            return MutationOutcome(
                status="rejected",
                result={"safety_decision": safe_decision},
                reason="device_unavailable",
                audit={
                    "safety_decision": safe_decision,
                    "failure_category": "device_unavailable",
                },
            )

        safe_decision = self._safe_decision(
            gateway_result.decision.as_dict()
        )
        if not gateway_result.decision.allowed:
            return MutationOutcome(
                status="rejected",
                result={"safety_decision": safe_decision},
                reason="safety_gateway_denied",
                audit={"safety_decision": safe_decision},
            )
        if gateway_result.command is None:
            return MutationOutcome(
                status="rejected",
                result={"safety_decision": safe_decision},
                reason="command_not_created",
                audit={"safety_decision": safe_decision},
            )

        command_id = str(gateway_result.command["command_id"])
        authoritative = (
            self._gateway.command(command_id)
            or gateway_result.command
        )
        command = {
            key: authoritative.get(key)
            for key in self._COMMAND_FIELDS
        }
        phase = str(command["phase"])
        if phase == "confirmed":
            status: MutationOutcomeStatus = "confirmed"
            reason: MutationOutcomeReason | None = None
        elif phase in {"failed", "timed_out", "cancelled"}:
            status = "failed"
            reason = "command_lifecycle_failed"
        else:
            status = "pending"
            reason = None

        return MutationOutcome(
            status=status,
            result={
                "command": command,
                "safety_decision": safe_decision,
            },
            reason=reason,
            audit={
                "safety_decision": safe_decision,
                "command_id": command_id,
                "phase": phase,
                "outcome": status,
                **(
                    {"failure_category": command.get("failure_reason")}
                    if command.get("failure_reason")
                    else {}
                ),
            },
        )

    @staticmethod
    def _safe_decision(
        decision: dict[str, object],
    ) -> dict[str, object]:
        return {
            key: decision[key]
            for key in (
                "allowed",
                "reason",
                "node_id",
                "capability_id",
                "action",
                "risk_level",
                "verification_status",
                "node_hardware_verified",
                "execution_mode",
            )
        }
