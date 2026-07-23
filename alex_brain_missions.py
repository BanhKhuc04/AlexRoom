from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from alex_orchestration import MissionExecutor
from alex_safety import CommandGateway, SafetyDecision
from alex_store import AlexStore


MissionOutcomeStatus = Literal[
    "rejected",
    "pending",
    "running",
    "completed",
    "failed",
]
MissionOutcomeReason = Literal[
    "mission_not_found",
    "mission_not_brain_allowed",
    "mission_disabled",
    "mission_preflight_failed",
    "mission_execution_failed",
]


@dataclass(frozen=True)
class MissionAuditEvent:
    stage: str
    level: Literal["info", "warning"]
    details: dict[str, object]


@dataclass(frozen=True)
class MissionOutcome:
    status: MissionOutcomeStatus
    result: dict[str, object]
    reason: MissionOutcomeReason | None
    audit_events: tuple[MissionAuditEvent, ...]


class MissionRecordStore(Protocol):
    def get_record(
        self,
        domain: str,
        record_id: str,
    ) -> dict[str, object] | None: ...


def preflight_stored_steps(
    definition: dict[str, object],
    gateway: CommandGateway,
    *,
    steps_field: str,
) -> dict[str, object]:
    """Validate and authorize a complete stored action list without executing it."""

    steps = definition.get(steps_field)
    if not isinstance(steps, list) or not steps:
        return _preflight_denied(
            step_count=0,
            step_index=None,
            capability=None,
            reason=f"invalid_{steps_field}",
        )

    requests: list[tuple[str, str, str]] = []
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            return _preflight_denied(
                len(steps),
                index,
                None,
                "malformed_step",
            )
        node_id = raw_step.get("node_id", "esp01")
        capability = raw_step.get("target")
        action = raw_step.get("action")
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(capability, str)
            or not capability
            or not isinstance(action, str)
            or not action
        ):
            return _preflight_denied(
                len(steps),
                index,
                capability if isinstance(capability, str) else None,
                "malformed_step",
            )
        if capability.lower() == "test_led" and action.lower() == "set":
            payload = (
                raw_step.get("payload")
                if isinstance(raw_step.get("payload"), dict)
                else {"value": raw_step.get("value")}
            )
            if (
                set(payload) != {"value"}
                or not isinstance(payload.get("value"), bool)
            ):
                return _preflight_denied(
                    len(steps),
                    index,
                    capability,
                    "invalid_boolean_payload",
                )
        requests.append((node_id, capability, action))

    decisions = gateway.authorize_batch(requests)
    if len(decisions) != len(requests):
        return _preflight_denied(
            len(steps),
            None,
            None,
            "incomplete_safety_preflight",
        )
    for index, decision in enumerate(decisions):
        if not decision.allowed:
            return _preflight_denied(
                len(steps),
                index,
                decision.capability_id,
                decision.reason,
                decision,
            )
    return {"allowed": True, "step_count": len(steps)}


def _preflight_denied(
    step_count: int,
    step_index: int | None,
    capability: str | None,
    reason: str,
    decision: SafetyDecision | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "allowed": False,
        "step_count": step_count,
        "denied_step_index": step_index,
        "denied_capability": capability,
        "reason": reason,
    }
    if decision is not None:
        result["safety_decision"] = {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "node_id": decision.node_id,
            "capability_id": decision.capability_id,
            "action": decision.action,
            "risk_level": decision.risk_level,
            "verification_status": decision.verification_status,
            "execution_mode": decision.execution_mode,
        }
    return result


class StoredSafeMissionExecutor:
    """Lookup, authorize and preflight a stored mission before existing execution."""

    def __init__(
        self,
        store: AlexStore | MissionRecordStore,
        mission_executor: MissionExecutor,
        gateway: CommandGateway,
    ) -> None:
        self._store = store
        self._mission_executor = mission_executor
        self._gateway = gateway

    def execute(self, mission_id: str) -> MissionOutcome:
        events: list[MissionAuditEvent] = []
        mission = self._store.get_record("missions", mission_id)
        events.append(
            MissionAuditEvent(
                "mission_lookup",
                "info" if mission is not None else "warning",
                {
                    "mission_id": mission_id,
                    "outcome": "found" if mission is not None else "not_found",
                },
            )
        )
        if mission is None:
            return self._rejected(
                mission_id,
                "mission_not_found",
                events,
            )

        brain_allowed = mission.get("brain_allowed") is True
        events.append(
            MissionAuditEvent(
                "mission_brain_allowed",
                "info" if brain_allowed else "warning",
                {
                    "mission_id": mission_id,
                    "allowed": brain_allowed,
                },
            )
        )
        if not brain_allowed:
            return self._rejected(
                mission_id,
                "mission_not_brain_allowed",
                events,
            )

        enabled, enabled_field = self._enabled_state(mission)
        events.append(
            MissionAuditEvent(
                "mission_enabled_state",
                "info" if enabled else "warning",
                {
                    "mission_id": mission_id,
                    "enabled": enabled,
                    "source_field": enabled_field,
                },
            )
        )
        if not enabled:
            return self._rejected(
                mission_id,
                "mission_disabled",
                events,
            )

        preflight = self._preflight(mission)
        events.append(
            MissionAuditEvent(
                "mission_preflight",
                "info" if preflight["allowed"] else "warning",
                {
                    "mission_id": mission_id,
                    **preflight,
                },
            )
        )
        if not preflight["allowed"]:
            return MissionOutcome(
                status="rejected",
                result={
                    "mission_id": mission_id,
                    "preflight": preflight,
                },
                reason="mission_preflight_failed",
                audit_events=tuple(events),
            )

        events.append(
            MissionAuditEvent(
                "mission_execution_start",
                "info",
                {
                    "mission_id": mission_id,
                    "step_count": preflight["step_count"],
                },
            )
        )
        try:
            run = self._mission_executor.run(mission, "brain")
        except Exception:
            events.append(
                MissionAuditEvent(
                    "mission_execution_outcome",
                    "warning",
                    {
                        "mission_id": mission_id,
                        "outcome": "failed",
                        "failure_category": "mission_execution_failed",
                    },
                )
            )
            return MissionOutcome(
                status="failed",
                result={"mission_id": mission_id},
                reason="mission_execution_failed",
                audit_events=tuple(events),
            )

        run_status = str(run.get("status", "failed"))
        if run_status == "completed":
            status: MissionOutcomeStatus = "completed"
            reason: MissionOutcomeReason | None = None
        elif run_status in {"pending", "running"}:
            status = run_status
            reason = None
        else:
            status = "failed"
            reason = "mission_execution_failed"
        events.append(
            MissionAuditEvent(
                "mission_execution_outcome",
                "info" if status == "completed" else "warning",
                {
                    "mission_id": mission_id,
                    "mission_run_id": str(run.get("mission_id", "")),
                    "outcome": run_status,
                },
            )
        )
        return MissionOutcome(
            status=status,
            result={"mission": run},
            reason=reason,
            audit_events=tuple(events),
        )

    @staticmethod
    def _enabled_state(
        mission: dict[str, object],
    ) -> tuple[bool, str]:
        if "enabled" in mission and mission["enabled"] is not True:
            return False, "enabled"
        if "active" in mission and mission["active"] is not True:
            return False, "active"
        if mission.get("disabled") is True:
            return False, "disabled"
        if mission.get("status") in {"disabled", "inactive"}:
            return False, "status"
        if "enabled" in mission:
            return True, "enabled"
        if "active" in mission:
            return True, "active"
        return True, "default_active"

    def _preflight(
        self,
        mission: dict[str, object],
    ) -> dict[str, object]:
        return preflight_stored_steps(
            mission,
            self._gateway,
            steps_field="steps",
        )

    @staticmethod
    def _rejected(
        mission_id: str,
        reason: MissionOutcomeReason,
        events: list[MissionAuditEvent],
    ) -> MissionOutcome:
        return MissionOutcome(
            status="rejected",
            result={"mission_id": mission_id},
            reason=reason,
            audit_events=tuple(events),
        )
