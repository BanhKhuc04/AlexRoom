from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from alex_command_verification import (
    CommandVerificationState,
    FeedbackDisposition,
    VerificationFeedbackKind,
    command_verification_result,
    evaluate_command_feedback,
    pending_command_verification,
    verification_expectation,
)


REQUESTED_AT = "2026-07-24T10:00:00+00:00"
SENT_AT = "2026-07-24T10:00:01+00:00"
ACK_AT = "2026-07-24T10:00:02+00:00"
CONFIRMED_AT = "2026-07-24T10:00:03+00:00"


def command(
    *,
    command_id: str = "cmd-a",
    value: bool = True,
    phase: str = "waiting_ack",
    source: str = "local_software",
    failure_reason: str | None = None,
) -> dict[str, object]:
    return {
        "command_id": command_id,
        "node_id": "esp01",
        "target": "test_led",
        "action": "set",
        "desired_state": {"on": value},
        "reported_state": {"on": not value},
        "phase": phase,
        "source": source,
        "requested_at": REQUESTED_AT,
        "sent_at": SENT_AT,
        "acknowledged_at": (
            ACK_AT
            if phase
            in {
                "accepted",
                "waiting_reported_state",
                "confirmed",
            }
            else None
        ),
        "confirmed_at": (
            CONFIRMED_AT if phase == "confirmed" else None
        ),
        "failure_reason": failure_reason,
    }


def feedback(
    current: dict[str, object] | None,
    payload: object,
    *,
    kind: VerificationFeedbackKind,
    source: str = "mqtt",
):
    return evaluate_command_feedback(
        current,
        payload,
        kind=kind,
        source=source,
        protocol_version=1,
        expected_node_id="esp01",
        expected_capability_id="test_led",
    )


def ack(
    command_id: str = "cmd-a",
    *,
    node_id: str = "esp01",
    status: object = "accepted",
) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "nodeId": node_id,
        "commandId": command_id,
        "status": status,
        "timestamp": 123,
    }


def reported(
    command_id: str = "cmd-a",
    *,
    node_id: str = "esp01",
    target: str = "test_led",
    value: object = True,
) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "nodeId": node_id,
        "commandId": command_id,
        "target": target,
        "state": {"on": value},
        "timestamp": 456,
    }


def test_contracts_are_frozen_and_json_safe() -> None:
    expectation = verification_expectation(command())
    pending = pending_command_verification(command())
    result = command_verification_result(command())
    with pytest.raises(FrozenInstanceError):
        expectation.command_id = "other"  # type: ignore[misc]
    encoded = json.dumps(
        {
            "expectation": expectation.to_compact_dict(),
            "pending": pending.to_compact_dict(),
            "result": result.to_compact_dict(),
        },
        allow_nan=False,
    )
    assert json.loads(encoded)["result"]["state"] == "published"


@pytest.mark.parametrize(
    ("phase", "reason", "expected"),
    (
        ("queued", None, CommandVerificationState.REQUESTED),
        ("sending", None, CommandVerificationState.AUTHORIZED),
        ("waiting_ack", None, CommandVerificationState.PUBLISHED),
        ("accepted", None, CommandVerificationState.ACKNOWLEDGED),
        (
            "waiting_reported_state",
            None,
            CommandVerificationState.WAITING_FOR_VERIFICATION,
        ),
        ("confirmed", None, CommandVerificationState.VERIFIED),
        (
            "failed",
            "mqtt_publish_failed",
            CommandVerificationState.PUBLISH_FAILED,
        ),
        (
            "failed",
            "reported_state_mismatch",
            CommandVerificationState.VERIFICATION_FAILED,
        ),
        (
            "timed_out",
            "ack_timeout",
            CommandVerificationState.ACK_TIMEOUT,
        ),
        (
            "timed_out",
            "reported_state_timeout",
            CommandVerificationState.VERIFICATION_TIMEOUT,
        ),
        ("cancelled", None, CommandVerificationState.CANCELLED),
        ("future", None, CommandVerificationState.UNKNOWN),
    ),
)
def test_command_phase_maps_to_explicit_verification_state(
    phase: str,
    reason: str | None,
    expected: CommandVerificationState,
) -> None:
    result = command_verification_result(
        command(phase=phase, failure_reason=reason)
    )
    assert result.state is expected


def test_acknowledged_is_not_verified() -> None:
    result = feedback(
        command(),
        ack(),
        kind=VerificationFeedbackKind.ACK,
    )
    assert result.disposition is FeedbackDisposition.ACKNOWLEDGED
    assert result.acknowledged is True
    assert result.verified is False
    assert result.observed_value is None


@pytest.mark.parametrize("value", [True, False])
def test_exact_reported_boolean_verifies_on_and_off(value: bool) -> None:
    current = command(
        value=value,
        phase="waiting_reported_state",
    )
    result = feedback(
        current,
        reported(value=value),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert result.disposition is FeedbackDisposition.VERIFIED
    assert result.expected_value is value
    assert result.observed_value is value
    assert result.verified is True


def test_wrong_command_id_cannot_cross_match_concurrent_commands() -> None:
    command_a = command(command_id="cmd-a", value=True)
    command_b_ack = ack(command_id="cmd-b")
    result = feedback(
        command_a,
        command_b_ack,
        kind=VerificationFeedbackKind.ACK,
    )
    assert result.disposition is FeedbackDisposition.WRONG_COMMAND
    assert result.verified is False


def test_wrong_node_and_capability_are_rejected() -> None:
    wrong_node = feedback(
        command(),
        ack(node_id="esp02"),
        kind=VerificationFeedbackKind.ACK,
    )
    wrong_capability = feedback(
        command(phase="waiting_reported_state"),
        reported(target="relay_1"),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert wrong_node.disposition is FeedbackDisposition.WRONG_NODE
    assert (
        wrong_capability.disposition
        is FeedbackDisposition.WRONG_CAPABILITY
    )


def test_wrong_reported_state_is_failure_not_verification() -> None:
    result = feedback(
        command(value=True, phase="waiting_reported_state"),
        reported(value=False),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert result.disposition is FeedbackDisposition.STATE_MISMATCH
    assert result.verified is False


@pytest.mark.parametrize(
    "payload",
    (
        None,
        "not-json",
        {},
        {"protocolVersion": True},
        {"protocolVersion": 2},
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": "",
        },
    ),
)
def test_malformed_feedback_fails_closed(payload: object) -> None:
    result = feedback(
        command(),
        payload,
        kind=VerificationFeedbackKind.ACK,
    )
    assert result.disposition is FeedbackDisposition.MALFORMED
    assert result.verified is False


@pytest.mark.parametrize("value", [1, 0, "true", "false", None, {}])
def test_reported_state_requires_strict_boolean(value: object) -> None:
    result = feedback(
        command(phase="waiting_reported_state"),
        reported(value=value),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert result.disposition is FeedbackDisposition.MALFORMED
    assert result.verified is False


def test_duplicate_ack_and_report_are_idempotent() -> None:
    duplicate_ack = feedback(
        command(phase="waiting_reported_state"),
        ack(),
        kind=VerificationFeedbackKind.ACK,
    )
    duplicate_report = feedback(
        command(phase="confirmed"),
        reported(value=True),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert duplicate_ack.disposition is FeedbackDisposition.DUPLICATE
    assert (
        duplicate_report.disposition
        is FeedbackDisposition.DUPLICATE
    )


@pytest.mark.parametrize("phase", ["failed", "timed_out", "cancelled"])
def test_late_feedback_never_retroactively_verifies(phase: str) -> None:
    result = feedback(
        command(phase=phase),
        reported(value=True),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert result.disposition is FeedbackDisposition.LATE
    assert result.verified is False


def test_reported_state_before_ack_is_out_of_order() -> None:
    result = feedback(
        command(phase="waiting_ack"),
        reported(value=True),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert result.disposition is FeedbackDisposition.OUT_OF_ORDER
    assert result.verified is False


def test_unknown_command_and_source_mismatch_fail_closed() -> None:
    unknown = feedback(
        None,
        ack("cmd-missing"),
        kind=VerificationFeedbackKind.ACK,
    )
    source_mismatch = feedback(
        command(source="simulated"),
        ack(),
        kind=VerificationFeedbackKind.ACK,
        source="mqtt",
    )
    assert unknown.disposition is FeedbackDisposition.UNKNOWN_COMMAND
    assert (
        source_mismatch.disposition
        is FeedbackDisposition.SOURCE_MISMATCH
    )


def test_simulator_confirmation_is_not_physical_verification() -> None:
    result = command_verification_result(
        command(phase="confirmed", source="simulated")
    )
    assert result.verified is True
    assert result.simulated is True
    assert result.physically_verified is False
    assert result.verification_source == "simulator_reported_state"


def test_real_confirmation_requires_reported_state_evidence() -> None:
    result = command_verification_result(command(phase="confirmed"))
    assert result.verified is True
    assert result.physically_verified is True
    assert result.verification_source == "mqtt_reported_state"
    assert result.verified_at == CONFIRMED_AT


def test_device_timestamp_is_not_fabricated_as_core_observed_at() -> None:
    result = feedback(
        command(phase="waiting_reported_state"),
        reported(value=True),
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    compact = result.to_compact_dict()
    assert "timestamp" not in compact
    assert "observed_at" not in compact


def test_same_feedback_produces_same_result() -> None:
    current = command(phase="waiting_reported_state")
    payload = reported(value=True)
    left = feedback(
        current,
        payload,
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    right = feedback(
        current,
        payload,
        kind=VerificationFeedbackKind.REPORTED_STATE,
    )
    assert left == right
    assert left.to_compact_dict() == right.to_compact_dict()


def test_pure_verification_module_has_no_io_or_authorization_dependency() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alex_command_verification.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "paho.mqtt",
        "sqlite3",
        "AlexStore",
        "SafetyPolicy",
        "CommandGateway",
        "time.monotonic",
        "datetime.now",
        "threading",
        ".publish(",
    )
    assert all(marker not in source for marker in forbidden)
