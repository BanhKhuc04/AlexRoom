from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from alex_brain_integration import (
    C7_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_mutations import CommandGatewaySetTestLedExecutor
from alex_brain_tools import BrainChatRequest, BrainChatResponse
from alex_command_verification import (
    CommandVerificationState,
    command_verification_result,
)
from alex_hardware import CommandService, RealtimeHub
from alex_safety import (
    CapabilityRegistry,
    CommandGateway,
    GatewayExecutionError,
    SafetyPolicy,
)
from alex_store import AlexStore


@dataclass
class HardwareHarness:
    store: AlexStore
    hub: RealtimeHub
    service: CommandService
    gateway: CommandGateway
    published: list[dict[str, object]]
    events: list[dict[str, object]]

    def request(self, value: bool):
        return self.gateway.request(
            node_id="esp01",
            capability_id="test_led",
            action="set",
            payload={"value": value},
            origin="test",
        )

    def ack(self, command_id: str, **changes: object) -> bool:
        payload = {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": command_id,
            "status": "accepted",
            **changes,
        }
        return self.service.handle_ack(payload, "simulated")

    def reported(
        self,
        command_id: str,
        value: object,
        **changes: object,
    ) -> bool:
        payload = {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": command_id,
            "target": "test_led",
            "state": {"on": value},
            **changes,
        }
        return self.service.handle_reported(payload, "simulated")


@pytest.fixture
def harness(tmp_path: Path) -> HardwareHarness:
    store = AlexStore(tmp_path / "alex.db")
    store.migrate()
    published: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    def publish(
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
    ) -> bool:
        published.append(
            {
                "topic": topic,
                "payload": json.loads(payload),
                "qos": qos,
                "retain": retain,
            }
        )
        return True

    hub = RealtimeHub()
    hub.add_listener(events.append)
    service = CommandService(
        store,
        publish,
        hub,
        ack_timeout=2,
        reported_timeout=3,
        max_retries=0,
        simulator_mode=True,
    )
    gateway = CommandGateway(
        SafetyPolicy(CapabilityRegistry(), simulator_mode=True),
        service,
    )
    service.handle_heartbeat(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "online": True,
        },
        "simulated",
    )
    published.clear()
    events.clear()
    return HardwareHarness(
        store=store,
        hub=hub,
        service=service,
        gateway=gateway,
        published=published,
        events=events,
    )


@pytest.mark.parametrize("value", [True, False], ids=["on", "off"])
def test_test_led_golden_path_requires_matching_reported_state(
    harness: HardwareHarness,
    value: bool,
) -> None:
    result = harness.request(value)
    assert result.decision.allowed is True
    command = result.command
    assert command is not None
    command_id = command["command_id"]
    assert len(harness.published) == 1
    assert harness.published[0]["payload"]["commandId"] == command_id

    published = command_verification_result(
        harness.service.command(command_id)
    )
    assert published.state is CommandVerificationState.PUBLISHED
    assert published.verified is False

    assert harness.ack(command_id) is True
    acknowledged = command_verification_result(
        harness.service.command(command_id)
    )
    assert (
        acknowledged.state
        is CommandVerificationState.WAITING_FOR_VERIFICATION
    )
    assert acknowledged.acknowledged is True
    assert acknowledged.verified is False

    assert harness.reported(command_id, value) is True
    verified = command_verification_result(
        harness.service.command(command_id)
    )
    assert verified.state is CommandVerificationState.VERIFIED
    assert verified.observed_value is value
    assert verified.verified is True
    assert verified.physically_verified is False
    assert verified.verification_source == "simulator_reported_state"
    assert len(harness.published) == 1


def test_publish_failure_is_not_success_and_has_one_attempt(
    tmp_path: Path,
) -> None:
    store = AlexStore(tmp_path / "publish-failed.db")
    store.migrate()
    calls = 0

    def fail_publish(*_args) -> bool:
        nonlocal calls
        calls += 1
        return False

    service = CommandService(
        store,
        fail_publish,
        RealtimeHub(),
        max_retries=0,
        simulator_mode=True,
    )
    gateway = CommandGateway(
        SafetyPolicy(CapabilityRegistry(), simulator_mode=True),
        service,
    )
    service.handle_heartbeat(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "online": True,
        },
        "simulated",
    )
    result = gateway.request(
        node_id="esp01",
        capability_id="test_led",
        action="set",
        payload={"value": True},
    )
    command = service.command(result.command["command_id"])
    verification = command_verification_result(command)
    assert calls == 1
    assert verification.state is CommandVerificationState.PUBLISH_FAILED
    assert verification.verified is False


def test_ack_timeout_is_deterministic_and_does_not_republish(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    internal = harness.service._commands[command_id]
    deadline = internal["deadline"]
    assert harness.service.process_timeouts(
        now_monotonic=deadline,
    ) == 1
    result = command_verification_result(
        harness.service.command(command_id)
    )
    assert result.state is CommandVerificationState.ACK_TIMEOUT
    assert result.verified is False
    assert len(harness.published) == 1


def test_reported_timeout_after_ack_is_not_verified(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    harness.ack(command_id)
    deadline = harness.service._commands[command_id]["deadline"]
    assert harness.service.process_timeouts(
        now_monotonic=deadline,
    ) == 1
    result = command_verification_result(
        harness.service.command(command_id)
    )
    assert (
        result.state
        is CommandVerificationState.VERIFICATION_TIMEOUT
    )
    assert result.acknowledged is True
    assert result.verified is False
    assert len(harness.published) == 1


@pytest.mark.parametrize(
    "mutator",
    (
        lambda command_id: {
            "commandId": "cmd-wrong",
        },
        lambda command_id: {
            "commandId": command_id,
            "nodeId": "esp02",
        },
    ),
    ids=["wrong-command", "wrong-node"],
)
def test_wrong_ack_cannot_advance_command(
    harness: HardwareHarness,
    mutator,
) -> None:
    command_id = harness.request(True).command["command_id"]
    assert harness.ack(command_id, **mutator(command_id)) is False
    assert (
        harness.service.command(command_id)["phase"]
        == "waiting_ack"
    )


def test_wrong_capability_and_malformed_state_do_not_mutate_truth(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    harness.ack(command_id)
    before = harness.service.device()["reported_state"]["test_led"]
    assert harness.reported(
        command_id,
        True,
        target="relay_1",
    ) is False
    assert harness.reported(command_id, "false") is False
    assert (
        harness.service.device()["reported_state"]["test_led"]
        == before
    )
    assert (
        harness.service.command(command_id)["phase"]
        == "waiting_reported_state"
    )


def test_wrong_reported_state_fails_without_fake_success(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    harness.ack(command_id)
    assert harness.reported(command_id, False) is True
    result = command_verification_result(
        harness.service.command(command_id)
    )
    assert result.state is CommandVerificationState.VERIFICATION_FAILED
    assert result.failure_reason == "reported_state_mismatch"
    assert result.verified is False


def test_duplicate_feedback_does_not_execute_or_transition_twice(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    assert harness.ack(command_id)
    assert harness.ack(command_id)
    assert harness.reported(command_id, True)
    assert harness.reported(command_id, True) is False
    assert harness.service.command(command_id)["phase"] == "confirmed"
    assert len(harness.published) == 1


def test_late_feedback_after_timeout_cannot_restore_success(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    deadline = harness.service._commands[command_id]["deadline"]
    harness.service.process_timeouts(now_monotonic=deadline)
    assert harness.ack(command_id) is False
    assert harness.reported(command_id, True) is False
    command = harness.service.command(command_id)
    assert command["phase"] == "timed_out"
    assert command["confirmed_at"] is None


def test_out_of_order_report_updates_truth_but_not_command_success(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    assert harness.reported(command_id, True) is False
    assert (
        harness.service.device()["reported_state"]["test_led"]["on"]
        is True
    )
    assert harness.service.command(command_id)["phase"] == "waiting_ack"
    assert harness.service.command(command_id)["confirmed_at"] is None


def test_same_capability_commands_are_serialized_fail_safe(
    harness: HardwareHarness,
) -> None:
    first_id = harness.request(True).command["command_id"]
    with pytest.raises(
        GatewayExecutionError,
        match="test_led_command_in_progress",
    ):
        harness.request(False)
    assert len(harness.published) == 1
    harness.ack(first_id)
    harness.reported(first_id, True)
    second = harness.request(False)
    assert second.command["command_id"] != first_id
    assert len(harness.published) == 2


def test_device_restart_fails_active_command_without_confirmation(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    assert harness.service.handle_reported(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": "boot",
            "target": "test_led",
            "state": {"on": False},
        },
        "simulated",
    ) is False
    command = harness.service.command(command_id)
    assert command["phase"] == "failed"
    assert (
        command["failure_reason"]
        == "device_restarted_during_command"
    )
    assert command["confirmed_at"] is None


def test_safety_denial_and_unsupported_capability_never_publish(
    harness: HardwareHarness,
) -> None:
    for capability in (
        "relay_1",
        "relay_2",
        "relay_3",
        "relay_4",
        "unknown_capability",
    ):
        result = harness.gateway.request(
            node_id="esp01",
            capability_id=capability,
            action="set",
            payload={"value": True},
        )
        assert result.decision.allowed is False
        assert result.command is None
    assert harness.published == []
    assert harness.service._commands == {}


def test_offline_device_creates_no_verification_or_publish(
    harness: HardwareHarness,
) -> None:
    harness.service.mark_offline("simulated")
    with pytest.raises(GatewayExecutionError, match="esp01_offline"):
        harness.request(True)
    assert harness.published == []
    assert harness.service._commands == {}


def test_hardware_mode_rejects_simulator_feedback(
    tmp_path: Path,
) -> None:
    store = AlexStore(tmp_path / "hardware.db")
    store.migrate()
    published: list[object] = []
    service = CommandService(
        store,
        lambda *args: published.append(args) or True,
        RealtimeHub(),
        max_retries=0,
        simulator_mode=False,
    )
    gateway = CommandGateway(
        SafetyPolicy(CapabilityRegistry(), simulator_mode=False),
        service,
    )
    service.handle_heartbeat(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "online": True,
        },
        "mqtt",
    )
    command_id = gateway.request(
        node_id="esp01",
        capability_id="test_led",
        action="set",
        payload={"value": True},
    ).command["command_id"]
    assert service.handle_ack(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": command_id,
            "status": "accepted",
        },
        "simulated",
    ) is False
    assert service.command(command_id)["phase"] == "waiting_ack"


def test_mocked_mqtt_reported_state_is_physical_evidence(
    tmp_path: Path,
) -> None:
    store = AlexStore(tmp_path / "mqtt-evidence.db")
    store.migrate()
    service = CommandService(
        store,
        lambda *_args: True,
        RealtimeHub(),
        max_retries=0,
        simulator_mode=False,
    )
    gateway = CommandGateway(
        SafetyPolicy(CapabilityRegistry(), simulator_mode=False),
        service,
    )
    service.handle_heartbeat(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "online": True,
        },
        "mqtt",
    )
    command_id = gateway.request(
        node_id="esp01",
        capability_id="test_led",
        action="set",
        payload={"value": True},
    ).command["command_id"]
    assert service.handle_ack(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": command_id,
            "status": "accepted",
        },
        "mqtt",
    )
    assert service.handle_reported(
        {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "commandId": command_id,
            "target": "test_led",
            "state": {"on": True},
        },
        "mqtt",
    )
    verification = command_verification_result(
        service.command(command_id)
    )
    assert verification.verified is True
    assert verification.physically_verified is True
    assert verification.verification_source == "mqtt_reported_state"


def test_audit_and_realtime_reuse_command_lifecycle(
    harness: HardwareHarness,
) -> None:
    command_id = harness.request(True).command["command_id"]
    harness.ack(command_id)
    harness.reported(command_id, True)
    stored_types = {
        event["event_type"]
        for event in harness.store.command_events(command_id)
    }
    realtime_types = {event["type"] for event in harness.events}
    required = {
        "command_created",
        "command_sent",
        "command_ack",
        "command_waiting_reported",
        "command_confirmed",
    }
    assert required.issubset(stored_types)
    assert required.issubset(realtime_types)


class FixedBrainClient:
    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        return BrainChatResponse(
            request_id=request.request_id,
            assistant_text="Proposal only.",
            tool_calls=[
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                }
            ],
        )


def test_brain_tool_result_is_pending_after_publish_only(
    harness: HardwareHarness,
) -> None:
    integration = CoreBrainIntegration(
        FixedBrainClient(),
        system_status_reader=lambda: {},
        device_list_reader=lambda: {},
        audit=lambda *_args: None,
        execution_allowlist=C7_EXECUTION_ALLOWLIST,
        set_test_led_executor=CommandGatewaySetTestLedExecutor(
            harness.gateway
        ),
    )
    response = integration.chat(
        BrainChatRequest(
            request_id="req-c2g",
            user_text="Bật test_led của esp01",
        )
    )
    result = response.tool_results[0]
    assert result.status == "pending"
    assert result.result["command"]["phase"] == "waiting_ack"
    assert result.result["verification"]["state"] == "published"
    assert result.result["verification"]["verified"] is False
    assert len(harness.published) == 1


def test_brain_boundary_has_no_mqtt_client_access() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in (
            "alex_brain_tools.py",
            "alex_brain_integration.py",
            "alex_brain_context_envelope.py",
            "brain_service/service.py",
        )
    )
    for marker in (
        "paho.mqtt",
        "mqtt_client",
        ".publish(",
        "COMMAND_TOPIC",
        "ACK_TOPIC",
        "REPORTED_TOPIC",
    ):
        assert marker not in sources
