from __future__ import annotations

import unittest

from pydantic import ValidationError

from alex_brain_tools import (
    BRAIN_TOOL_REGISTRY,
    MAX_RECORD_ID_LENGTH,
    MAX_REQUEST_ID_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_TOOL_CALLS,
    TOOL_NAMES,
    BrainChatRequest,
    BrainChatResponse,
    BrainToolBoundary,
    BrainToolBoundaryError,
    BrainToolCall,
)
from alex_safety import CapabilityRegistry


class FakeRecordStore:
    def __init__(self, records: dict[tuple[str, str], dict[str, object]] | None = None) -> None:
        self.records = records or {}

    def get_record(self, domain: str, record_id: str) -> dict[str, object] | None:
        return self.records.get((domain, record_id))


class BrainContractTests(unittest.TestCase):
    def assert_invalid_call(self, name: str, arguments: object) -> None:
        with self.assertRaises(ValidationError):
            BrainToolCall.model_validate({"name": name, "arguments": arguments})

    def test_exact_six_tool_allowlist(self) -> None:
        expected = (
            "system_status",
            "list_devices",
            "set_test_led",
            "set_room_mode",
            "run_safe_mission",
            "run_safe_automation",
        )
        self.assertEqual(TOOL_NAMES, expected)
        self.assertEqual(tuple(BRAIN_TOOL_REGISTRY), expected)
        self.assertEqual(len(BRAIN_TOOL_REGISTRY), 6)

    def test_unknown_tool_is_rejected_case_sensitively(self) -> None:
        self.assert_invalid_call("unknown_tool", {})
        self.assert_invalid_call("System_Status", {})

    def test_relay_tool_is_rejected(self) -> None:
        self.assert_invalid_call("relay_1", {"value": True})

    def test_mqtt_publish_is_rejected(self) -> None:
        self.assert_invalid_call("mqtt_publish", {"topic": "alex/device/esp01/command"})

    def test_set_test_led_accepts_boolean_only(self) -> None:
        call = BrainToolCall(name="set_test_led", arguments={"value": True})
        self.assertEqual(call.arguments, {"value": True})
        for invalid in (1, 0, "true", "false", None):
            with self.subTest(invalid=invalid):
                self.assert_invalid_call("set_test_led", {"value": invalid})

    def test_set_test_led_cannot_supply_node_id(self) -> None:
        self.assert_invalid_call(
            "set_test_led",
            {"value": True, "node_id": "esp01"},
        )

    def test_set_test_led_cannot_supply_target_or_capability(self) -> None:
        self.assert_invalid_call(
            "set_test_led",
            {"value": True, "target": "relay_1"},
        )
        self.assert_invalid_call(
            "set_test_led",
            {"value": True, "capability": "relay_1"},
        )

    def test_set_test_led_has_fixed_core_mapping(self) -> None:
        definition = BRAIN_TOOL_REGISTRY["set_test_led"]
        self.assertEqual(
            dict(definition.core_mapping),
            {"node_id": "esp01", "capability": "test_led", "action": "set"},
        )

    def test_room_mode_has_exact_allowlist(self) -> None:
        for mode in ("home", "away", "sleep", "study"):
            call = BrainToolCall(name="set_room_mode", arguments={"mode": mode})
            self.assertEqual(call.arguments["mode"], mode)
        for invalid in ("HOME", "vacation", "", 1):
            with self.subTest(invalid=invalid):
                self.assert_invalid_call("set_room_mode", {"mode": invalid})

    def test_mission_id_malformed_is_rejected(self) -> None:
        for invalid in ("", "   ", " leading", "trailing ", "x" * (MAX_RECORD_ID_LENGTH + 1), 7):
            with self.subTest(invalid=invalid):
                self.assert_invalid_call("run_safe_mission", {"mission_id": invalid})

    def test_automation_id_malformed_is_rejected(self) -> None:
        for invalid in ("", "\t", " leading", "trailing ", "x" * (MAX_RECORD_ID_LENGTH + 1), False):
            with self.subTest(invalid=invalid):
                self.assert_invalid_call("run_safe_automation", {"automation_id": invalid})

    def test_extra_arguments_are_rejected_for_every_shape(self) -> None:
        self.assert_invalid_call("system_status", {"unexpected": True})
        self.assert_invalid_call("list_devices", {"unexpected": True})
        self.assert_invalid_call("set_room_mode", {"mode": "home", "unexpected": True})

    def test_more_than_max_tool_calls_is_rejected(self) -> None:
        calls = [{"name": "system_status", "arguments": {}}] * (MAX_TOOL_CALLS + 1)
        with self.assertRaises(ValidationError):
            BrainChatResponse(
                request_id="req-1",
                assistant_text="",
                tool_calls=calls,
            )

    def test_exact_duplicate_calls_are_rejected_but_distinct_calls_remain_valid(
        self,
    ) -> None:
        duplicate = {
            "name": "run_safe_mission",
            "arguments": {"mission_id": "safe-mission"},
        }
        with self.assertRaises(ValidationError):
            BrainChatResponse(
                request_id="req-duplicate",
                assistant_text="",
                tool_calls=[duplicate, duplicate],
            )
        response = BrainChatResponse(
            request_id="req-distinct",
            assistant_text="",
            tool_calls=[
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                },
                {
                    "name": "set_test_led",
                    "arguments": {"value": False},
                },
            ],
        )
        self.assertEqual(len(response.tool_calls), 2)

    def test_request_id_and_chat_text_are_bounded(self) -> None:
        request = BrainChatRequest(
            request_id="r" * MAX_REQUEST_ID_LENGTH,
            user_text="u" * MAX_TEXT_LENGTH,
        )
        response = BrainChatResponse(
            request_id=request.request_id,
            assistant_text="a" * MAX_TEXT_LENGTH,
        )
        self.assertEqual(response.request_id, request.request_id)

        invalid_payloads = (
            {"request_id": "", "user_text": "hello"},
            {"request_id": " ", "user_text": "hello"},
            {"request_id": "r" * (MAX_REQUEST_ID_LENGTH + 1), "user_text": "hello"},
            {"request_id": "req", "user_text": ""},
            {"request_id": "req", "user_text": "u" * (MAX_TEXT_LENGTH + 1)},
            {"request_id": 1, "user_text": "hello"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                BrainChatRequest.model_validate(payload)

        with self.assertRaises(ValidationError):
            BrainChatResponse(
                request_id="req",
                assistant_text="a" * (MAX_TEXT_LENGTH + 1),
            )

    def test_request_and_record_ids_reject_control_characters(self) -> None:
        for control in ("\r", "\n", "\t", "\x00", "\x1f", "\x7f"):
            with self.subTest(control=repr(control)):
                with self.assertRaises(ValidationError):
                    BrainChatRequest(
                        request_id=f"req{control}injected",
                        user_text="safe",
                    )
                self.assert_invalid_call(
                    "run_safe_mission",
                    {"mission_id": f"mission{control}injected"},
                )
                self.assert_invalid_call(
                    "run_safe_automation",
                    {
                        "automation_id": (
                            f"automation{control}injected"
                        )
                    },
                )

    def test_response_cannot_embed_executable_generic_mqtt_structure(self) -> None:
        with self.assertRaises(ValidationError):
            BrainChatResponse.model_validate(
                {
                    "request_id": "req-1",
                    "assistant_text": "proposal only",
                    "tool_calls": [
                        {
                            "name": "set_test_led",
                            "arguments": {"value": True},
                            "mqtt": {
                                "topic": "alex/device/esp01/switch/relay_1/command",
                                "payload": "ON",
                            },
                        }
                    ],
                }
            )
        self.assert_invalid_call(
            "system_status",
            {
                "mqtt_publish": {
                    "topic": "alex/device/esp01/switch/relay_1/command",
                    "payload": "ON",
                }
            },
        )

    def test_stored_workflows_must_exist_and_be_brain_allowed(self) -> None:
        store = FakeRecordStore(
            {
                ("missions", "allowed-mission"): {"brain_allowed": True},
                ("missions", "denied-mission"): {"brain_allowed": False},
                ("automations", "allowed-automation"): {"brain_allowed": True},
                ("automations", "truthy-not-bool"): {"brain_allowed": 1},
            }
        )
        boundary = BrainToolBoundary(store)

        mission = boundary.validate_proposal(
            BrainToolCall(
                name="run_safe_mission",
                arguments={"mission_id": "allowed-mission"},
            )
        )
        automation = boundary.validate_proposal(
            BrainToolCall(
                name="run_safe_automation",
                arguments={"automation_id": "allowed-automation"},
            )
        )
        self.assertEqual(mission.arguments["mission_id"], "allowed-mission")
        self.assertEqual(automation.arguments["automation_id"], "allowed-automation")

        rejected = (
            ("run_safe_mission", {"mission_id": "missing"}, "mission_not_found"),
            ("run_safe_mission", {"mission_id": "denied-mission"}, "mission_not_brain_allowed"),
            ("run_safe_automation", {"automation_id": "missing"}, "automation_not_found"),
            (
                "run_safe_automation",
                {"automation_id": "truthy-not-bool"},
                "automation_not_brain_allowed",
            ),
        )
        for name, arguments, reason in rejected:
            with self.subTest(reason=reason), self.assertRaises(BrainToolBoundaryError) as raised:
                boundary.validate_proposal(BrainToolCall(name=name, arguments=arguments))
            self.assertEqual(raised.exception.reason, reason)

    def test_boundary_only_returns_proposal_and_has_no_execute_method(self) -> None:
        boundary = BrainToolBoundary(FakeRecordStore())
        proposal = boundary.validate_proposal(
            BrainToolCall(name="set_test_led", arguments={"value": False})
        )
        self.assertEqual(
            dict(proposal.core_mapping),
            {"node_id": "esp01", "capability": "test_led", "action": "set"},
        )
        self.assertFalse(hasattr(boundary, "execute"))
        self.assertFalse(hasattr(proposal, "execute"))

    def test_existing_relay_restrictions_remain_unchanged(self) -> None:
        registry = CapabilityRegistry()
        for relay_id in range(1, 5):
            relay = registry.capability("esp01", f"relay_{relay_id}")
            self.assertIsNotNone(relay)
            self.assertEqual(relay.risk_level, "restricted")
            self.assertFalse(relay.command_allowed)

    def test_existing_test_led_safety_truth_remains_unchanged(self) -> None:
        led = CapabilityRegistry().capability("esp01", "test_led")
        self.assertIsNotNone(led)
        self.assertEqual(led.verification_status, "basic_physical_validated")
        self.assertTrue(led.command_allowed)
        self.assertEqual(led.supported_actions, frozenset({"set"}))


if __name__ == "__main__":
    unittest.main()
