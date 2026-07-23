from __future__ import annotations

import inspect
import json
import unittest

from alex_brain_automations import (
    AutomationAuditEvent,
    AutomationOutcome,
)
from alex_brain_client import (
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
)
from alex_brain_integration import (
    C6B_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_missions import MissionOutcome
from alex_brain_mutations import MutationOutcome
from alex_brain_tools import BrainChatRequest, BrainChatResponse
from alex_safety import CapabilityRegistry


REQUEST = BrainChatRequest(
    request_id="req-c6b-policy",
    user_text="Chạy automation an toàn.",
)


def response_with(
    *calls: dict[str, object],
    assistant_text: str = "Brain proposal",
) -> BrainChatResponse:
    return BrainChatResponse.model_validate(
        {
            "request_id": REQUEST.request_id,
            "assistant_text": assistant_text,
            "tool_calls": list(calls),
        }
    )


class StubClient:
    def __init__(self, response: object) -> None:
        self.response = response

    def chat(self, request: BrainChatRequest):
        return self.response


class StoredExecutorSpy:
    def __init__(self, outcome: MissionOutcome | AutomationOutcome) -> None:
        self.outcome = outcome
        self.ids: list[str] = []

    def execute(self, record_id: str):
        self.ids.append(record_id)
        return self.outcome


class MutationSpy:
    def __init__(self) -> None:
        self.values: list[bool] = []

    def execute(self, value: bool) -> MutationOutcome:
        self.values.append(value)
        return MutationOutcome(
            status="pending",
            result={
                "command": {
                    "command_id": "cmd-c6b",
                    "phase": "waiting_ack",
                }
            },
            reason=None,
            audit={
                "command_id": "cmd-c6b",
                "phase": "waiting_ack",
                "outcome": "pending",
            },
        )


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


class CoreBrainC6BPolicyTests(unittest.TestCase):
    def integration(
        self,
        response: object,
        *,
        automation_outcome: AutomationOutcome | None = None,
    ):
        mission = StoredExecutorSpy(
            MissionOutcome(
                status="completed",
                result={"mission": {"status": "completed"}},
                reason=None,
                audit_events=(),
            )
        )
        automation = StoredExecutorSpy(
            automation_outcome
            or AutomationOutcome(
                status="completed",
                result={"automation": {"matched": True}},
                reason=None,
                audit_events=(),
            )
        )
        mutation = MutationSpy()
        status_calls: list[bool] = []
        device_calls: list[bool] = []
        audit = AuditSpy()
        service = CoreBrainIntegration(
            StubClient(response),
            system_status_reader=lambda: (
                status_calls.append(True) or {"source": "core-status"}
            ),
            device_list_reader=lambda: (
                device_calls.append(True)
                or {"source": "core-devices", "items": []}
            ),
            audit=audit,
            execution_allowlist=C6B_EXECUTION_ALLOWLIST,
            set_test_led_executor=mutation,
            safe_mission_executor=mission,
            safe_automation_executor=automation,
        )
        return (
            service,
            mission,
            automation,
            mutation,
            status_calls,
            device_calls,
            audit,
        )

    def test_c6b_execution_allowlist_is_exact(self) -> None:
        self.assertEqual(
            C6B_EXECUTION_ALLOWLIST,
            (
                "system_status",
                "list_devices",
                "set_test_led",
                "run_safe_mission",
                "run_safe_automation",
            ),
        )

    def test_set_room_mode_remains_disabled(self) -> None:
        service, mission, automation, mutation, status, devices, _ = (
            self.integration(
                response_with(
                    {
                        "name": "set_room_mode",
                        "arguments": {"mode": "study"},
                    }
                )
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(
            result.tool_results[0].reason,
            "tool_not_enabled_in_c6b",
        )
        self.assertEqual(mission.ids, [])
        self.assertEqual(automation.ids, [])
        self.assertEqual(mutation.values, [])
        self.assertEqual(status, [])
        self.assertEqual(devices, [])

    def test_brain_can_supply_only_automation_id(self) -> None:
        injected = (
            ("actions", []),
            ("schedule", "0 0 * * *"),
            ("mission_id", "override"),
            ("node_id", "esp01"),
            ("target", "test_led"),
            ("topic", "alex/device/esp01/command"),
            ("conditions", []),
            ("trigger", {"type": "manual"}),
        )
        for field, value in injected:
            with self.subTest(field=field):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Injected",
                    "tool_calls": [
                        {
                            "name": "run_safe_automation",
                            "arguments": {
                                "automation_id": "safe-automation",
                                field: value,
                            },
                        }
                    ],
                }
                service, mission, automation, mutation, status, devices, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError) as raised:
                    service.chat(REQUEST)
                self.assertEqual(
                    raised.exception.code,
                    "invalid_brain_response",
                )
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_automation_plus_room_mode_batch_is_atomic(self) -> None:
        service, mission, automation, mutation, status, devices, _ = (
            self.integration(
                response_with(
                    {
                        "name": "run_safe_automation",
                        "arguments": {
                            "automation_id": "safe-automation"
                        },
                    },
                    {
                        "name": "set_room_mode",
                        "arguments": {"mode": "away"},
                    },
                )
            )
        )
        result = service.chat(REQUEST)
        self.assertTrue(
            all(item.status == "rejected" for item in result.tool_results)
        )
        self.assertEqual(mission.ids, [])
        self.assertEqual(automation.ids, [])
        self.assertEqual(mutation.values, [])
        self.assertEqual(status, [])
        self.assertEqual(devices, [])

    def test_unknown_bypass_tools_are_structurally_rejected(self) -> None:
        for name in (
            "mqtt_publish",
            "set_relay",
            "relay_1",
            "create_automation",
            "update_automation",
            "run_raw_action",
        ):
            with self.subTest(name=name):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Bypass",
                    "tool_calls": [{"name": name, "arguments": {}}],
                }
                service, mission, automation, mutation, status, devices, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError):
                    service.chat(REQUEST)
                self.assertEqual(mission.ids, [])
                self.assertEqual(automation.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_all_previously_enabled_tools_still_work(self) -> None:
        service, mission, automation, mutation, status, devices, _ = (
            self.integration(
                response_with(
                    {"name": "system_status", "arguments": {}},
                    {"name": "list_devices", "arguments": {}},
                    {
                        "name": "set_test_led",
                        "arguments": {"value": True},
                    },
                    {
                        "name": "run_safe_mission",
                        "arguments": {"mission_id": "safe-mission"},
                    },
                )
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["ok", "ok", "pending", "completed"],
        )
        self.assertEqual(status, [True])
        self.assertEqual(devices, [True])
        self.assertEqual(mutation.values, [True])
        self.assertEqual(mission.ids, ["safe-mission"])
        self.assertEqual(automation.ids, [])

    def test_assistant_claim_cannot_override_failed_or_running_result(self) -> None:
        cases = (
            AutomationOutcome(
                status="failed",
                result={"automation": {"matched": False}},
                reason="automation_execution_failed",
                audit_events=(),
            ),
            AutomationOutcome(
                status="running",
                result={"automation": {"matched": True}},
                reason=None,
                audit_events=(),
            ),
        )
        for outcome in cases:
            with self.subTest(status=outcome.status):
                service, *_ = self.integration(
                    response_with(
                        {
                            "name": "run_safe_automation",
                            "arguments": {
                                "automation_id": "safe-automation"
                            },
                        },
                        assistant_text="Automation completed successfully.",
                    ),
                    automation_outcome=outcome,
                )
                result = service.chat(REQUEST)
                self.assertEqual(
                    result.tool_results[0].status,
                    outcome.status,
                )

    def test_audit_is_correlated_bounded_and_secret_free(self) -> None:
        outcome = AutomationOutcome(
            status="rejected",
            result={"automation_id": "denied-automation"},
            reason="automation_not_brain_allowed",
            audit_events=(
                AutomationAuditEvent(
                    "automation_lookup",
                    "info",
                    {
                        "automation_id": "denied-automation",
                        "outcome": "found",
                    },
                ),
                AutomationAuditEvent(
                    "automation_brain_allowed",
                    "warning",
                    {
                        "automation_id": "denied-automation",
                        "allowed": False,
                    },
                ),
            ),
        )
        service, *_, audit = self.integration(
            response_with(
                {
                    "name": "run_safe_automation",
                    "arguments": {
                        "automation_id": "denied-automation"
                    },
                }
            ),
            automation_outcome=outcome,
        )
        service.chat(REQUEST)
        serialized = json.dumps(audit.records)
        self.assertIn("automation_brain_allowed", serialized)
        self.assertIn(REQUEST.request_id, serialized)
        for secret in (
            REQUEST.user_text,
            "ALEX_API_KEY",
            "ALEX_BRAIN_CLIENT_KEY",
            "MQTT_PASSWORD",
        ):
            self.assertNotIn(secret, serialized)

    def test_automation_path_reuses_existing_orchestration_without_mqtt(self) -> None:
        source = inspect.getsource(
            __import__("alex_brain_automations")
        )
        self.assertNotIn("mqtt_client", source)
        self.assertNotIn(".publish(", source)
        self.assertIn(
            "self._automation_executor.evaluate(",
            source,
        )
        self.assertIn("preflight_stored_steps(", source)

    def test_relay_registry_remains_restricted(self) -> None:
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
            execution_allowlist=C6B_EXECUTION_ALLOWLIST,
        )
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "brain_disabled")


if __name__ == "__main__":
    unittest.main()
