from __future__ import annotations

import json
import unittest

from alex_brain_client import (
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
)
from alex_brain_integration import (
    C7_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_mutations import MutationOutcome
from alex_brain_room_mode import AuthoritativeRoomModeExecutor
from alex_brain_tools import (
    BRAIN_TOOL_REGISTRY,
    TOOL_NAMES,
    BrainChatRequest,
    BrainChatResponse,
)
from alex_safety import CapabilityRegistry


REQUEST = BrainChatRequest(
    request_id="req-c7-policy",
    user_text="Chuyển sang chế độ học.",
)


def response_with(*calls: dict[str, object]) -> BrainChatResponse:
    return BrainChatResponse.model_validate(
        {
            "request_id": REQUEST.request_id,
            "assistant_text": "Brain proposal",
            "tool_calls": list(calls),
        }
    )


class StubClient:
    def __init__(self, response: object) -> None:
        self.response = response

    def chat(self, request: BrainChatRequest):
        return self.response


class MutationSpy:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.values: list[bool] = []

    def execute(self, value: bool) -> MutationOutcome:
        self.values.append(value)
        self.trace.append(f"led:{value}")
        return MutationOutcome(
            status="pending",
            result={
                "command": {
                    "command_id": "cmd-c7",
                    "phase": "waiting_ack",
                }
            },
            reason=None,
            audit={
                "command_id": "cmd-c7",
                "phase": "waiting_ack",
                "outcome": "pending",
            },
        )


class StoredExecutorSpy:
    def __init__(self, trace: list[str], kind: str) -> None:
        self.trace = trace
        self.kind = kind
        self.ids: list[str] = []

    def execute(self, record_id: str):
        self.ids.append(record_id)
        self.trace.append(f"{self.kind}:{record_id}")
        raise AssertionError("unexpected orchestration execution")


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


class CoreBrainC7PolicyTests(unittest.TestCase):
    def integration(self, response: object):
        trace: list[str] = []
        current = {"mode": "home"}

        def set_mode(mode):
            previous = current["mode"]
            current["mode"] = mode
            trace.append(f"mode:{mode}")
            return {
                "accepted": True,
                "mode": mode,
                "previous_mode": previous,
                "logical_mode_updated": True,
                "physical_actions": [],
                "physical_result": (
                    "not_requested_restricted_capabilities"
                ),
            }

        mutation = MutationSpy(trace)
        mission = StoredExecutorSpy(trace, "mission")
        automation = StoredExecutorSpy(trace, "automation")
        audit = AuditSpy()
        service = CoreBrainIntegration(
            StubClient(response),
            system_status_reader=lambda: {"source": "core-status"},
            device_list_reader=lambda: {
                "source": "core-devices",
                "items": [],
            },
            audit=audit,
            execution_allowlist=C7_EXECUTION_ALLOWLIST,
            set_test_led_executor=mutation,
            safe_mission_executor=mission,
            safe_automation_executor=automation,
            room_mode_executor=AuthoritativeRoomModeExecutor(set_mode),
        )
        return (
            service,
            current,
            mutation,
            mission,
            automation,
            trace,
            audit,
        )

    def test_c7_allowlist_is_exact_six_tool_registry(self) -> None:
        self.assertEqual(C7_EXECUTION_ALLOWLIST, TOOL_NAMES)
        self.assertEqual(tuple(BRAIN_TOOL_REGISTRY), TOOL_NAMES)
        self.assertEqual(len(C7_EXECUTION_ALLOWLIST), 6)
        for forbidden in (
            "mqtt_publish",
            "set_relay",
            "execute_command",
            "run_shell",
            "gpio",
        ):
            self.assertNotIn(forbidden, C7_EXECUTION_ALLOWLIST)

    def test_all_four_canonical_modes_are_accepted(self) -> None:
        for mode in ("home", "away", "sleep", "study"):
            with self.subTest(mode=mode):
                service, current, mutation, mission, automation, trace, _ = (
                    self.integration(
                        response_with(
                            {
                                "name": "set_room_mode",
                                "arguments": {"mode": mode},
                            }
                        )
                    )
                )
                result = service.chat(REQUEST).tool_results[0]
                self.assertEqual(result.status, "ok")
                self.assertEqual(result.result["mode"], mode)
                self.assertEqual(result.result["physical_actions"], [])
                self.assertEqual(current["mode"], mode)
                self.assertEqual(trace, [f"mode:{mode}"])
                self.assertEqual(mutation.values, [])
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])

    def test_invalid_modes_are_structurally_rejected(self) -> None:
        for mode in (
            "night",
            "vacation",
            "HOME",
            " study ",
            None,
            1,
            True,
        ):
            with self.subTest(mode=mode):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Invalid mode",
                    "tool_calls": [
                        {
                            "name": "set_room_mode",
                            "arguments": {"mode": mode},
                        }
                    ],
                }
                service, current, mutation, mission, automation, trace, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError) as raised:
                    service.chat(REQUEST)
                self.assertEqual(
                    raised.exception.code,
                    "invalid_brain_response",
                )
                self.assertEqual(current["mode"], "home")
                self.assertEqual(trace, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])

    def test_room_mode_rejects_extra_hardware_arguments(self) -> None:
        injected = (
            ("physical_actions", []),
            ("node_id", "esp01"),
            ("target", "test_led"),
            ("capability", "relay_1"),
            ("relay", "relay_1"),
            ("topic", "alex/device/esp01/command"),
            ("mission_id", "study-mission"),
            ("automation_id", "study-automation"),
        )
        for field, value in injected:
            with self.subTest(field=field):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Injected",
                    "tool_calls": [
                        {
                            "name": "set_room_mode",
                            "arguments": {
                                "mode": "study",
                                field: value,
                            },
                        }
                    ],
                }
                service, current, mutation, mission, automation, trace, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError):
                    service.chat(REQUEST)
                self.assertEqual(current["mode"], "home")
                self.assertEqual(trace, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])

    def test_explicit_mode_then_led_executes_in_provider_order(self) -> None:
        service, current, mutation, mission, automation, trace, _ = (
            self.integration(
                response_with(
                    {
                        "name": "set_room_mode",
                        "arguments": {"mode": "study"},
                    },
                    {
                        "name": "set_test_led",
                        "arguments": {"value": True},
                    },
                )
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["ok", "pending"],
        )
        self.assertEqual(trace, ["mode:study", "led:True"])
        self.assertEqual(current["mode"], "study")
        self.assertEqual(mutation.values, [True])
        self.assertEqual(mission.ids, [])
        self.assertEqual(automation.ids, [])

    def test_malformed_or_unknown_second_tool_causes_zero_execution(self) -> None:
        bad_calls = (
            {
                "name": "set_test_led",
                "arguments": {"value": "true"},
            },
            {"name": "mqtt_publish", "arguments": {}},
            {"name": "set_relay", "arguments": {}},
        )
        for bad_call in bad_calls:
            with self.subTest(bad_call=bad_call):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Partial bypass",
                    "tool_calls": [
                        {
                            "name": "set_room_mode",
                            "arguments": {"mode": "study"},
                        },
                        bad_call,
                    ],
                }
                service, current, mutation, mission, automation, trace, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError):
                    service.chat(REQUEST)
                self.assertEqual(current["mode"], "home")
                self.assertEqual(trace, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])

    def test_exact_duplicate_mutation_calls_cause_zero_execution(self) -> None:
        duplicate = {
            "name": "set_room_mode",
            "arguments": {"mode": "study"},
        }
        malformed = {
            "request_id": REQUEST.request_id,
            "assistant_text": "Duplicate replay",
            "tool_calls": [duplicate, duplicate],
        }
        service, current, mutation, mission, automation, trace, _ = (
            self.integration(malformed)
        )
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "invalid_brain_response")
        self.assertEqual(current["mode"], "home")
        self.assertEqual(trace, [])
        self.assertEqual(mutation.values, [])
        self.assertEqual(mission.ids, [])
        self.assertEqual(automation.ids, [])

    def test_assistant_hardware_claim_does_not_enter_core_result(self) -> None:
        response = BrainChatResponse.model_validate(
            {
                "request_id": REQUEST.request_id,
                "assistant_text": (
                    "Đã tắt toàn bộ thiết bị và chuyển sang sleep."
                ),
                "tool_calls": [
                    {
                        "name": "set_room_mode",
                        "arguments": {"mode": "sleep"},
                    }
                ],
            }
        )
        service, *_ = self.integration(response)
        result = service.chat(REQUEST).tool_results[0].result
        self.assertEqual(result["mode"], "sleep")
        self.assertEqual(result["physical_actions"], [])
        self.assertNotIn("hardware_changed", result)
        self.assertNotIn("relay_changed", result)
        self.assertNotIn("executed_devices", result)

    def test_audit_records_bounded_logical_mutation_without_secrets(self) -> None:
        service, *_, audit = self.integration(
            response_with(
                {
                    "name": "set_room_mode",
                    "arguments": {"mode": "away"},
                }
            )
        )
        service.chat(REQUEST)
        serialized = json.dumps(audit.records)
        self.assertIn("room_mode_validated", serialized)
        self.assertIn("room_mode_result", serialized)
        self.assertIn('"physical_action_count": 0', serialized)
        self.assertIn(REQUEST.request_id, serialized)
        for secret in (
            REQUEST.user_text,
            "ALEX_API_KEY",
            "ALEX_BRAIN_CLIENT_KEY",
            "MQTT_PASSWORD",
        ):
            self.assertNotIn(secret, serialized)

    def test_relay_registry_remains_exactly_restricted(self) -> None:
        registry = CapabilityRegistry()
        for relay_id in range(1, 5):
            relay = registry.capability("esp01", f"relay_{relay_id}")
            self.assertFalse(relay.command_allowed)
            self.assertEqual(relay.verification_status, "restricted")
            self.assertEqual(relay.risk_level, "restricted")
            self.assertEqual(relay.allowed_modes, frozenset())
            self.assertEqual(
                relay.restriction_reason,
                "hardware_not_verified_and_no_safety_interlock",
            )

    def test_core_remains_fail_safe_when_brain_is_disabled(self) -> None:
        service = CoreBrainIntegration(
            CoreBrainClient(CoreBrainConfig(enabled=False)),
            system_status_reader=lambda: {"status": "ok"},
            device_list_reader=lambda: {"items": []},
            audit=lambda *_: None,
            execution_allowlist=C7_EXECUTION_ALLOWLIST,
        )
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "brain_disabled")


if __name__ == "__main__":
    unittest.main()
