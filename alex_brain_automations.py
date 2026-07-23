from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from alex_brain_missions import preflight_stored_steps
from alex_orchestration import AutomationExecutor
from alex_safety import CommandGateway
from alex_store import AlexStore


AutomationOutcomeStatus = Literal[
    "rejected",
    "pending",
    "running",
    "completed",
    "failed",
]
AutomationOutcomeReason = Literal[
    "automation_not_found",
    "automation_not_brain_allowed",
    "automation_disabled",
    "automation_preflight_failed",
    "automation_execution_failed",
]


@dataclass(frozen=True)
class AutomationAuditEvent:
    stage: str
    level: Literal["info", "warning"]
    details: dict[str, object]


@dataclass(frozen=True)
class AutomationOutcome:
    status: AutomationOutcomeStatus
    result: dict[str, object]
    reason: AutomationOutcomeReason | None
    audit_events: tuple[AutomationAuditEvent, ...]


class AutomationRecordStore(Protocol):
    def get_record(
        self,
        domain: str,
        record_id: str,
    ) -> dict[str, object] | None: ...


class StoredSafeAutomationExecutor:
    """Authorize stored inline actions before existing automation evaluation."""

    def __init__(
        self,
        store: AlexStore | AutomationRecordStore,
        automation_executor: AutomationExecutor,
        gateway: CommandGateway,
    ) -> None:
        self._store = store
        self._automation_executor = automation_executor
        self._gateway = gateway

    def execute(self, automation_id: str) -> AutomationOutcome:
        events: list[AutomationAuditEvent] = []
        automation = self._store.get_record("automations", automation_id)
        events.append(
            AutomationAuditEvent(
                "automation_lookup",
                "info" if automation is not None else "warning",
                {
                    "automation_id": automation_id,
                    "outcome": (
                        "found" if automation is not None else "not_found"
                    ),
                },
            )
        )
        if automation is None:
            return self._rejected(
                automation_id,
                "automation_not_found",
                events,
            )

        brain_allowed = automation.get("brain_allowed") is True
        events.append(
            AutomationAuditEvent(
                "automation_brain_allowed",
                "info" if brain_allowed else "warning",
                {
                    "automation_id": automation_id,
                    "allowed": brain_allowed,
                },
            )
        )
        if not brain_allowed:
            return self._rejected(
                automation_id,
                "automation_not_brain_allowed",
                events,
            )

        enabled = self._enabled_state(automation)
        events.append(
            AutomationAuditEvent(
                "automation_enabled_state",
                "info" if enabled else "warning",
                {
                    "automation_id": automation_id,
                    "enabled": enabled,
                    "source_field": "enabled",
                },
            )
        )
        if not enabled:
            return self._rejected(
                automation_id,
                "automation_disabled",
                events,
            )

        actions = automation.get("actions")
        action_count = len(actions) if isinstance(actions, list) else 0
        events.append(
            AutomationAuditEvent(
                "automation_resolution",
                "info",
                {
                    "automation_id": automation_id,
                    "target_type": "inline_actions_via_mission_executor",
                    "action_count": action_count,
                },
            )
        )
        preflight = preflight_stored_steps(
            automation,
            self._gateway,
            steps_field="actions",
        )
        events.append(
            AutomationAuditEvent(
                "automation_preflight",
                "info" if preflight["allowed"] else "warning",
                {
                    "automation_id": automation_id,
                    **preflight,
                },
            )
        )
        if not preflight["allowed"]:
            return AutomationOutcome(
                status="rejected",
                result={
                    "automation_id": automation_id,
                    "preflight": preflight,
                },
                reason="automation_preflight_failed",
                audit_events=tuple(events),
            )

        events.append(
            AutomationAuditEvent(
                "automation_execution_start",
                "info",
                {
                    "automation_id": automation_id,
                    "trigger_type": "manual",
                    "action_count": action_count,
                },
            )
        )
        try:
            evaluation = self._automation_executor.evaluate(
                automation,
                {"type": "manual"},
            )
        except Exception:
            return self._failed(automation_id, events)

        matched = evaluation.get("matched") is True
        mission = evaluation.get("mission")
        mission_status = (
            str(mission.get("status", "failed"))
            if isinstance(mission, dict)
            else "not_started"
        )
        if matched and mission_status == "completed":
            status: AutomationOutcomeStatus = "completed"
            reason: AutomationOutcomeReason | None = None
        elif matched and mission_status in {"pending", "running"}:
            status = mission_status
            reason = None
        else:
            status = "failed"
            reason = "automation_execution_failed"
        events.append(
            AutomationAuditEvent(
                "automation_execution_outcome",
                "info" if status == "completed" else "warning",
                {
                    "automation_id": automation_id,
                    "matched": matched,
                    "blocked_reason": evaluation.get("blocked_reason"),
                    "mission_status": mission_status,
                    "outcome": status,
                },
            )
        )
        return AutomationOutcome(
            status=status,
            result={"automation": evaluation},
            reason=reason,
            audit_events=tuple(events),
        )

    @staticmethod
    def _enabled_state(automation: dict[str, object]) -> bool:
        if automation.get("enabled") is not True:
            return False
        if "active" in automation and automation["active"] is not True:
            return False
        if automation.get("disabled") is True:
            return False
        return automation.get("status") not in {"disabled", "inactive"}

    @staticmethod
    def _rejected(
        automation_id: str,
        reason: AutomationOutcomeReason,
        events: list[AutomationAuditEvent],
    ) -> AutomationOutcome:
        return AutomationOutcome(
            status="rejected",
            result={"automation_id": automation_id},
            reason=reason,
            audit_events=tuple(events),
        )

    @staticmethod
    def _failed(
        automation_id: str,
        events: list[AutomationAuditEvent],
    ) -> AutomationOutcome:
        events.append(
            AutomationAuditEvent(
                "automation_execution_outcome",
                "warning",
                {
                    "automation_id": automation_id,
                    "outcome": "failed",
                    "failure_category": "automation_execution_failed",
                },
            )
        )
        return AutomationOutcome(
            status="failed",
            result={"automation_id": automation_id},
            reason="automation_execution_failed",
            audit_events=tuple(events),
        )
