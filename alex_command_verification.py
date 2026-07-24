from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class CommandVerificationState(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    PUBLISHED = "published"
    ACKNOWLEDGED = "acknowledged"
    WAITING_FOR_VERIFICATION = "waiting_for_verification"
    VERIFIED = "verified"
    DENIED = "denied"
    PUBLISH_FAILED = "publish_failed"
    ACK_TIMEOUT = "ack_timeout"
    VERIFICATION_TIMEOUT = "verification_timeout"
    VERIFICATION_FAILED = "verification_failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class VerificationFeedbackKind(str, Enum):
    ACK = "ack"
    REPORTED_STATE = "reported_state"


class FeedbackDisposition(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    VERIFIED = "verified"
    DUPLICATE = "duplicate"
    LATE = "late"
    OUT_OF_ORDER = "out_of_order"
    UNKNOWN_COMMAND = "unknown_command"
    WRONG_COMMAND = "wrong_command"
    WRONG_NODE = "wrong_node"
    WRONG_CAPABILITY = "wrong_capability"
    SOURCE_MISMATCH = "source_mismatch"
    STATE_MISMATCH = "state_mismatch"
    DEVICE_REJECTED = "device_rejected"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class VerificationExpectation:
    command_id: str
    node_id: str
    capability_id: str
    action: str
    expected_value: bool
    simulated: bool

    def to_compact_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "action": self.action,
            "expected_value": self.expected_value,
            "simulated": self.simulated,
        }


@dataclass(frozen=True, slots=True)
class PendingCommandVerification:
    expectation: VerificationExpectation
    state: CommandVerificationState
    requested_at: str | None
    sent_at: str | None
    acknowledged_at: str | None
    confirmed_at: str | None

    def to_compact_dict(self) -> dict[str, object]:
        return {
            "expectation": self.expectation.to_compact_dict(),
            "state": self.state.value,
            "requested_at": self.requested_at,
            "sent_at": self.sent_at,
            "acknowledged_at": self.acknowledged_at,
            "confirmed_at": self.confirmed_at,
        }


@dataclass(frozen=True, slots=True)
class CommandVerificationResult:
    command_id: str
    node_id: str
    capability_id: str
    intended_action: str
    intended_value: bool | None
    observed_value: bool | None
    state: CommandVerificationState
    verification_source: str
    acknowledged: bool
    verified: bool
    physically_verified: bool
    simulated: bool
    requested_at: str | None
    published_at: str | None
    acknowledged_at: str | None
    verified_at: str | None
    failure_reason: str | None

    def to_compact_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "intended_action": self.intended_action,
            "intended_value": self.intended_value,
            "observed_value": self.observed_value,
            "state": self.state.value,
            "verification_source": self.verification_source,
            "acknowledged": self.acknowledged,
            "verified": self.verified,
            "physically_verified": self.physically_verified,
            "simulated": self.simulated,
            "requested_at": self.requested_at,
            "published_at": self.published_at,
            "acknowledged_at": self.acknowledged_at,
            "verified_at": self.verified_at,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class FeedbackEvaluation:
    disposition: FeedbackDisposition
    feedback_kind: VerificationFeedbackKind
    command_id: str | None
    node_id: str | None
    capability_id: str | None
    expected_value: bool | None
    observed_value: bool | None
    source: str
    acknowledged: bool
    verified: bool
    reason: str

    def to_compact_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "feedback_kind": self.feedback_kind.value,
            "command_id": self.command_id,
            "node_id": self.node_id,
            "capability_id": self.capability_id,
            "expected_value": self.expected_value,
            "observed_value": self.observed_value,
            "source": self.source,
            "acknowledged": self.acknowledged,
            "verified": self.verified,
            "reason": self.reason,
        }


def verification_expectation(
    command: Mapping[str, Any],
) -> VerificationExpectation:
    command_id = command.get("command_id")
    node_id = command.get("node_id")
    capability_id = command.get("target")
    action = command.get("action")
    desired = command.get("desired_state")
    expected_value = (
        desired.get("on")
        if isinstance(desired, Mapping)
        else None
    )
    if (
        not isinstance(command_id, str)
        or not command_id
        or not isinstance(node_id, str)
        or not node_id
        or not isinstance(capability_id, str)
        or not capability_id
        or not isinstance(action, str)
        or not action
        or not isinstance(expected_value, bool)
    ):
        raise ValueError("malformed_command_verification_expectation")
    return VerificationExpectation(
        command_id=command_id,
        node_id=node_id,
        capability_id=capability_id,
        action=action,
        expected_value=expected_value,
        simulated=command.get("source") == "simulated",
    )


def command_verification_result(
    command: Mapping[str, Any],
) -> CommandVerificationResult:
    command_id = _string(command.get("command_id"), "unknown")
    node_id = _string(command.get("node_id"), "unknown")
    capability_id = _string(command.get("target"), "unknown")
    action = _string(command.get("action"), "unknown")
    desired = command.get("desired_state")
    reported = command.get("reported_state")
    intended_value = _strict_on_value(desired)
    observed_value = _strict_on_value(reported)
    phase = _string(command.get("phase"), "unknown")
    failure_reason = _optional_string(command.get("failure_reason"))
    state = _verification_state(phase, failure_reason)
    simulated = command.get("source") == "simulated"
    acknowledged = isinstance(command.get("acknowledged_at"), str)
    verified = state is CommandVerificationState.VERIFIED
    if verified:
        verification_source = (
            "simulator_reported_state"
            if simulated
            else "mqtt_reported_state"
        )
    elif acknowledged:
        verification_source = (
            "simulator_ack"
            if simulated
            else "mqtt_ack"
        )
    elif isinstance(command.get("sent_at"), str):
        verification_source = "mqtt_publish"
    else:
        verification_source = "none"
    return CommandVerificationResult(
        command_id=command_id,
        node_id=node_id,
        capability_id=capability_id,
        intended_action=action,
        intended_value=intended_value,
        observed_value=observed_value,
        state=state,
        verification_source=verification_source,
        acknowledged=acknowledged,
        verified=verified,
        physically_verified=verified and not simulated,
        simulated=simulated,
        requested_at=_optional_string(command.get("requested_at")),
        published_at=_optional_string(command.get("sent_at")),
        acknowledged_at=_optional_string(
            command.get("acknowledged_at")
        ),
        verified_at=_optional_string(command.get("confirmed_at")),
        failure_reason=failure_reason,
    )


def pending_command_verification(
    command: Mapping[str, Any],
) -> PendingCommandVerification:
    result = command_verification_result(command)
    return PendingCommandVerification(
        expectation=verification_expectation(command),
        state=result.state,
        requested_at=result.requested_at,
        sent_at=result.published_at,
        acknowledged_at=result.acknowledged_at,
        confirmed_at=result.verified_at,
    )


def evaluate_command_feedback(
    command: Mapping[str, Any] | None,
    payload: object,
    *,
    kind: VerificationFeedbackKind,
    source: str,
    protocol_version: int,
    expected_node_id: str,
    expected_capability_id: str,
) -> FeedbackEvaluation:
    """Evaluate one feedback document without I/O, mutation, or authorization."""

    base = {
        "feedback_kind": kind,
        "source": source,
        "acknowledged": False,
        "verified": False,
    }
    if (
        not isinstance(payload, Mapping)
        or source not in {"mqtt", "simulated"}
        or isinstance(payload.get("protocolVersion"), bool)
        or payload.get("protocolVersion") != protocol_version
    ):
        return _feedback(
            FeedbackDisposition.MALFORMED,
            reason="malformed_feedback",
            **base,
        )
    command_id = payload.get("commandId")
    node_id = payload.get("nodeId")
    if not isinstance(command_id, str) or not command_id:
        return _feedback(
            FeedbackDisposition.MALFORMED,
            command_id=None,
            node_id=node_id if isinstance(node_id, str) else None,
            reason="missing_command_id",
            **base,
        )
    if not isinstance(node_id, str) or node_id != expected_node_id:
        return _feedback(
            FeedbackDisposition.WRONG_NODE,
            command_id=command_id,
            node_id=node_id if isinstance(node_id, str) else None,
            reason="wrong_node_id",
            **base,
        )

    observed_value: bool | None = None
    capability_id: str | None = None
    if kind is VerificationFeedbackKind.REPORTED_STATE:
        capability = payload.get("target")
        state = payload.get("state")
        if not isinstance(capability, str):
            return _feedback(
                FeedbackDisposition.MALFORMED,
                command_id=command_id,
                node_id=node_id,
                reason="missing_capability",
                **base,
            )
        capability_id = capability
        if capability != expected_capability_id:
            return _feedback(
                FeedbackDisposition.WRONG_CAPABILITY,
                command_id=command_id,
                node_id=node_id,
                capability_id=capability,
                reason="wrong_capability",
                **base,
            )
        observed_value = _strict_on_value(state)
        if observed_value is None:
            return _feedback(
                FeedbackDisposition.MALFORMED,
                command_id=command_id,
                node_id=node_id,
                capability_id=capability,
                reason="reported_state_requires_boolean_on",
                **base,
            )

    if command is None:
        return _feedback(
            FeedbackDisposition.UNKNOWN_COMMAND,
            command_id=command_id,
            node_id=node_id,
            capability_id=capability_id,
            observed_value=observed_value,
            reason="unknown_command_id",
            **base,
        )
    try:
        expectation = verification_expectation(command)
    except (TypeError, ValueError):
        return _feedback(
            FeedbackDisposition.MALFORMED,
            command_id=command_id,
            node_id=node_id,
            capability_id=capability_id,
            observed_value=observed_value,
            reason="malformed_command_expectation",
            **base,
        )
    expectation_fields = {
        "command_id": command_id,
        "node_id": node_id,
        "capability_id": (
            capability_id
            if capability_id is not None
            else expectation.capability_id
        ),
        "expected_value": expectation.expected_value,
        "observed_value": observed_value,
    }
    if command_id != expectation.command_id:
        return _feedback(
            FeedbackDisposition.WRONG_COMMAND,
            reason="wrong_command_id",
            **expectation_fields,
            **base,
        )
    if expectation.node_id != expected_node_id:
        return _feedback(
            FeedbackDisposition.WRONG_NODE,
            reason="command_node_mismatch",
            **expectation_fields,
            **base,
        )
    if expectation.capability_id != expected_capability_id:
        return _feedback(
            FeedbackDisposition.WRONG_CAPABILITY,
            reason="command_capability_mismatch",
            **expectation_fields,
            **base,
        )
    if expectation.simulated != (source == "simulated"):
        return _feedback(
            FeedbackDisposition.SOURCE_MISMATCH,
            reason="verification_source_mismatch",
            **expectation_fields,
            **base,
        )

    phase = _string(command.get("phase"), "unknown")
    if kind is VerificationFeedbackKind.ACK:
        status = payload.get("status")
        if not isinstance(status, str):
            return _feedback(
                FeedbackDisposition.MALFORMED,
                reason="ack_status_required",
                **expectation_fields,
                **base,
            )
        if phase in {"accepted", "waiting_reported_state"}:
            return _feedback(
                FeedbackDisposition.DUPLICATE,
                acknowledged=True,
                reason="duplicate_ack",
                **expectation_fields,
                feedback_kind=kind,
                source=source,
                verified=False,
            )
        if phase in {"confirmed", "failed", "timed_out", "cancelled"}:
            return _feedback(
                FeedbackDisposition.LATE,
                reason="late_ack",
                **expectation_fields,
                **base,
            )
        if phase != "waiting_ack":
            return _feedback(
                FeedbackDisposition.OUT_OF_ORDER,
                reason="ack_out_of_order",
                **expectation_fields,
                **base,
            )
        if status not in {"accepted", "duplicate"}:
            return _feedback(
                FeedbackDisposition.DEVICE_REJECTED,
                reason=_string(
                    payload.get("reason"),
                    "device_rejected",
                ),
                **expectation_fields,
                **base,
            )
        return _feedback(
            FeedbackDisposition.ACKNOWLEDGED,
            acknowledged=True,
            reason=f"device_{status}",
            **expectation_fields,
            feedback_kind=kind,
            source=source,
            verified=False,
        )

    if phase == "confirmed":
        return _feedback(
            (
                FeedbackDisposition.DUPLICATE
                if observed_value == expectation.expected_value
                else FeedbackDisposition.LATE
            ),
            reason="duplicate_reported_state",
            **expectation_fields,
            **base,
        )
    if phase in {"failed", "timed_out", "cancelled"}:
        return _feedback(
            FeedbackDisposition.LATE,
            reason="late_reported_state",
            **expectation_fields,
            **base,
        )
    if phase not in {"accepted", "waiting_reported_state"}:
        return _feedback(
            FeedbackDisposition.OUT_OF_ORDER,
            reason="reported_state_before_ack",
            **expectation_fields,
            **base,
        )
    if observed_value != expectation.expected_value:
        return _feedback(
            FeedbackDisposition.STATE_MISMATCH,
            reason="reported_state_mismatch",
            **expectation_fields,
            **base,
        )
    return _feedback(
        FeedbackDisposition.VERIFIED,
        acknowledged=True,
        verified=True,
        reason="reported_state_matches",
        **expectation_fields,
        feedback_kind=kind,
        source=source,
    )


def _feedback(
    disposition: FeedbackDisposition,
    *,
    feedback_kind: VerificationFeedbackKind,
    source: str,
    reason: str,
    command_id: str | None = None,
    node_id: str | None = None,
    capability_id: str | None = None,
    expected_value: bool | None = None,
    observed_value: bool | None = None,
    acknowledged: bool = False,
    verified: bool = False,
) -> FeedbackEvaluation:
    return FeedbackEvaluation(
        disposition=disposition,
        feedback_kind=feedback_kind,
        command_id=command_id,
        node_id=node_id,
        capability_id=capability_id,
        expected_value=expected_value,
        observed_value=observed_value,
        source=source,
        acknowledged=acknowledged,
        verified=verified,
        reason=reason,
    )


def _verification_state(
    phase: str,
    failure_reason: str | None,
) -> CommandVerificationState:
    if phase == "queued":
        return CommandVerificationState.REQUESTED
    if phase == "sending":
        return CommandVerificationState.AUTHORIZED
    if phase in {"waiting_ack", "retrying"}:
        return CommandVerificationState.PUBLISHED
    if phase == "accepted":
        return CommandVerificationState.ACKNOWLEDGED
    if phase == "waiting_reported_state":
        return CommandVerificationState.WAITING_FOR_VERIFICATION
    if phase == "confirmed":
        return CommandVerificationState.VERIFIED
    if phase == "cancelled":
        return CommandVerificationState.CANCELLED
    if phase == "timed_out":
        return (
            CommandVerificationState.ACK_TIMEOUT
            if failure_reason == "ack_timeout"
            else CommandVerificationState.VERIFICATION_TIMEOUT
        )
    if phase == "failed":
        return (
            CommandVerificationState.PUBLISH_FAILED
            if failure_reason == "mqtt_publish_failed"
            else CommandVerificationState.VERIFICATION_FAILED
        )
    return CommandVerificationState.UNKNOWN


def _strict_on_value(value: object) -> bool | None:
    if not isinstance(value, Mapping):
        return None
    on = value.get("on")
    return on if isinstance(on, bool) else None


def _string(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
