from __future__ import annotations

import unittest

from alex_brain_client import BrainClientError
from alex_brain_integration import (
    C5_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_mutations import (
    SET_TEST_LED_CORE_MAPPING,
    CommandGatewaySetTestLedExecutor,
    MutationOutcome,
)
from alex_brain_tools import BrainChatRequest, BrainChatResponse
from alex_safety import (
    GatewayResult,
    SafetyDecision,
)


REQUEST = BrainChatRequest(
    request_id="req-c5-policy",
    user_text="Bật đèn test.",
)


def response_with(
    *tool_calls: dict[str, object],
    assistant_text: str = "Brain proposal",
) -> BrainChatResponse:
    return BrainChatResponse.model_validate(
        {
            "request_id": REQUEST.request_id,
            "assistant_text": assistant_text,
            "tool_calls": list(tool_calls),
        }
    )


class StubClient:
    def __init__(self, response: object) -> None:
        self.response = response

    def chat(self, request: BrainChatRequest):
        return self.response


class AuditSpy:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def __call__(
        self,
        stage: str,
        level: str,
        details: dict[str, object],
    ) -> None:
        self.records.append(
            {"stage": stage, "level": level, "details": details}
        )


class MutationSpy:
    def __init__(
        self,
        outcome: MutationOutcome | None = None,
    ) -> None:
        self.values: list[bool] = []
        self.outcome = outcome or MutationOutcome(
            status="pending",
            result={
                "command": {
                    "command_id": "cmd-spy",
                    "phase": "waiting_ack",
                }
            },
            reason=None,
            audit={
                "command_id": "cmd-spy",
                "phase": "waiting_ack",
                "outcome": "pending",
            },
        )

    def execute(self, value: bool) -> MutationOutcome:
        self.values.append(value)
        return self.outcome


class ReadSpy:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> dict[str, object]:
        self.calls += 1
        return self.result


class RecordingGateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._command: dict[str, object] | None = None

    def request(self, **kwargs) -> GatewayResult:
        self.requests.append(kwargs)
        decision = SafetyDecision(
            allowed=True,
            reason="authorized",
            node_id=str(kwargs["node_id"]),
            capability_id=str(kwargs["capability_id"]),
            action=str(kwargs["action"]),
            risk_level="safe",
            verification_status="basic_physical_validated",
            node_hardware_verified=False,
            execution_mode="simulator",
        )
        value = kwargs["payload"]["value"]
        self._command = {
            "command_id": "cmd-recording",
            "node_id": kwargs["node_id"],
            "target": kwargs["capability_id"],
            "action": kwargs["action"],
            "desired_state": {"on": value},
            "reported_state": {"on": not value},
            "phase": "waiting_ack",
            "source": "simulated",
            "origin": kwargs["origin"],
            "created_at": "now",
            "requested_at": "now",
            "sent_at": "now",
            "acknowledged_at": None,
            "confirmed_at": None,
            "updated_at": "now",
            "retry_count": 0,
            "failure_reason": None,
            "ack_status": None,
            "deadline": 123.0,
        }
        return GatewayResult(decision, self._command)

    def command(self, command_id: str) -> dict[str, object] | None:
        return self._command


class CoreBrainC5PolicyTests(unittest.TestCase):
    def integration(
        self,
        response: object,
        *,
        mutation: MutationSpy | CommandGatewaySetTestLedExecutor | None = None,
        audit: AuditSpy | None = None,
    ) -> tuple[CoreBrainIntegration, MutationSpy, ReadSpy, ReadSpy, AuditSpy]:
        mutation_spy = mutation or MutationSpy()
        status = ReadSpy({"source": "core-status"})
        devices = ReadSpy({"source": "core-devices", "items": []})
        audit_spy = audit or AuditSpy()
        service = CoreBrainIntegration(
            StubClient(response),
            system_status_reader=status,
            device_list_reader=devices,
            audit=audit_spy,
            execution_allowlist=C5_EXECUTION_ALLOWLIST,
            set_test_led_executor=mutation_spy,
        )
        return service, mutation_spy, status, devices, audit_spy

    def test_c5_execution_allowlist_is_exact(self) -> None:
        self.assertEqual(
            C5_EXECUTION_ALLOWLIST,
            ("system_status", "list_devices", "set_test_led"),
        )

    def test_fixed_server_mapping_is_exact_for_true_and_false(self) -> None:
        self.assertEqual(
            SET_TEST_LED_CORE_MAPPING,
            {
                "node_id": "esp01",
                "capability": "test_led",
                "action": "set",
            },
        )
        for value in (True, False):
            with self.subTest(value=value):
                gateway = RecordingGateway()
                outcome = CommandGatewaySetTestLedExecutor(gateway).execute(
                    value
                )
                self.assertEqual(len(gateway.requests), 1)
                self.assertEqual(
                    gateway.requests[0],
                    {
                        "node_id": "esp01",
                        "capability_id": "test_led",
                        "action": "set",
                        "payload": {"value": value},
                        "origin": "brain",
                    },
                )
                self.assertEqual(outcome.status, "pending")
                self.assertEqual(
                    outcome.result["command"]["phase"],
                    "waiting_ack",
                )
                self.assertNotIn(
                    "deadline",
                    outcome.result["command"],
                )

    def test_valid_true_and_false_proposals_reach_mutation_executor(self) -> None:
        for value in (True, False):
            with self.subTest(value=value):
                service, mutation, _, _, _ = self.integration(
                    response_with(
                        {
                            "name": "set_test_led",
                            "arguments": {"value": value},
                        }
                    )
                )
                result = service.chat(REQUEST)
                self.assertEqual(mutation.values, [value])
                self.assertEqual(result.tool_results[0].status, "pending")

    def test_disabled_c5_tools_are_checkpoint_rejected(self) -> None:
        cases = (
            ("set_room_mode", {"mode": "study"}),
            ("run_safe_mission", {"mission_id": "safe-study"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-check"},
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                service, mutation, status, devices, _ = self.integration(
                    response_with(
                        {"name": name, "arguments": arguments}
                    )
                )
                result = service.chat(REQUEST)
                self.assertEqual(
                    result.tool_results[0].reason,
                    "tool_not_enabled_in_c5",
                )
                self.assertEqual(mutation.values, [])
                self.assertEqual(status.calls, 0)
                self.assertEqual(devices.calls, 0)

    def test_model_cannot_override_any_fixed_mapping_field(self) -> None:
        injected_fields = (
            ("node_id", "esp02"),
            ("capability", "relay_1"),
            ("action", "on"),
            ("target", "relay_1"),
            ("topic", "alex/device/esp01/relay_1"),
            ("gpio", 5),
        )
        for field, value in injected_fields:
            with self.subTest(field=field):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Injected",
                    "tool_calls": [
                        {
                            "name": "set_test_led",
                            "arguments": {
                                "value": True,
                                field: value,
                            },
                        }
                    ],
                }
                service, mutation, status, devices, _ = self.integration(
                    malformed
                )
                with self.assertRaises(BrainClientError) as raised:
                    service.chat(REQUEST)
                self.assertEqual(
                    raised.exception.code,
                    "invalid_brain_response",
                )
                self.assertEqual(mutation.values, [])
                self.assertEqual(status.calls, 0)
                self.assertEqual(devices.calls, 0)

    def test_unknown_or_hardware_bypass_tools_cannot_execute(self) -> None:
        for name in ("mqtt_publish", "set_relay", "relay_1", "set_device"):
            with self.subTest(name=name):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Bypass",
                    "tool_calls": [
                        {"name": name, "arguments": {}}
                    ],
                }
                service, mutation, status, devices, _ = self.integration(
                    malformed
                )
                with self.assertRaises(BrainClientError) as raised:
                    service.chat(REQUEST)
                self.assertEqual(
                    raised.exception.code,
                    "invalid_brain_response",
                )
                self.assertEqual(mutation.values, [])
                self.assertEqual(status.calls, 0)
                self.assertEqual(devices.calls, 0)

    def test_disallowed_mixed_batches_are_atomic(self) -> None:
        batches = (
            (
                {"name": "set_test_led", "arguments": {"value": True}},
                {"name": "set_room_mode", "arguments": {"mode": "sleep"}},
            ),
            (
                {"name": "set_test_led", "arguments": {"value": False}},
                {
                    "name": "run_safe_mission",
                    "arguments": {"mission_id": "safe-study"},
                },
            ),
            (
                {"name": "system_status", "arguments": {}},
                {"name": "set_room_mode", "arguments": {"mode": "away"}},
            ),
        )
        for calls in batches:
            with self.subTest(calls=calls):
                service, mutation, status, devices, _ = self.integration(
                    response_with(*calls)
                )
                result = service.chat(REQUEST)
                self.assertTrue(
                    all(item.status == "rejected" for item in result.tool_results)
                )
                self.assertEqual(mutation.values, [])
                self.assertEqual(status.calls, 0)
                self.assertEqual(devices.calls, 0)

    def test_enabled_system_status_and_set_test_led_can_both_process(self) -> None:
        service, mutation, status, _, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                },
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(status.calls, 1)
        self.assertEqual(mutation.values, [True])
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["ok", "pending"],
        )

    def test_read_tools_remain_authoritative(self) -> None:
        service, mutation, status, devices, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                {"name": "list_devices", "arguments": {}},
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(status.calls, 1)
        self.assertEqual(devices.calls, 1)
        self.assertEqual(mutation.values, [])
        self.assertEqual(
            [item.result["source"] for item in result.tool_results],
            ["core-status", "core-devices"],
        )

    def test_assistant_success_claim_cannot_override_pending_or_failed(self) -> None:
        pending = MutationSpy()
        service, _, _, _, _ = self.integration(
            response_with(
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                },
                assistant_text="Đèn đã bật và xác nhận thành công.",
            ),
            mutation=pending,
        )
        result = service.chat(REQUEST)
        self.assertEqual(result.tool_results[0].status, "pending")

        failed = MutationSpy(
            MutationOutcome(
                status="failed",
                result={
                    "command": {
                        "command_id": "cmd-failed",
                        "phase": "failed",
                        "failure_reason": "mqtt_publish_failed",
                    }
                },
                reason="command_lifecycle_failed",
                audit={
                    "command_id": "cmd-failed",
                    "phase": "failed",
                    "outcome": "failed",
                    "failure_category": "mqtt_publish_failed",
                },
            )
        )
        service, _, _, _, _ = self.integration(
            response_with(
                {
                    "name": "set_test_led",
                    "arguments": {"value": False},
                },
                assistant_text="Đèn đã tắt thành công.",
            ),
            mutation=failed,
        )
        result = service.chat(REQUEST)
        self.assertEqual(result.tool_results[0].status, "failed")
        self.assertEqual(
            result.tool_results[0].result["command"]["failure_reason"],
            "mqtt_publish_failed",
        )

if __name__ == "__main__":
    unittest.main()
