from __future__ import annotations

import inspect
import json
import unittest

from alex_brain_client import (
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
)
from alex_brain_integration import (
    C6A_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_missions import (
    MissionAuditEvent,
    MissionOutcome,
)
from alex_brain_mutations import MutationOutcome
from alex_brain_tools import BrainChatRequest, BrainChatResponse
from alex_safety import CapabilityRegistry


REQUEST = BrainChatRequest(
    request_id="req-c6a-policy",
    user_text="Chạy mission test đèn an toàn.",
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


class MissionExecutorSpy:
    def __init__(self, outcome: MissionOutcome) -> None:
        self.outcome = outcome
        self.ids: list[str] = []

    def execute(self, mission_id: str) -> MissionOutcome:
        self.ids.append(mission_id)
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
                    "command_id": "cmd-c6a",
                    "phase": "waiting_ack",
                }
            },
            reason=None,
            audit={
                "command_id": "cmd-c6a",
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


class CoreBrainC6APolicyTests(unittest.TestCase):
    def integration(
        self,
        response: object,
        *,
        mission_outcome: MissionOutcome | None = None,
    ):
        mission = MissionExecutorSpy(
            mission_outcome
            or MissionOutcome(
                status="completed",
                result={
                    "mission": {
                        "mission_id": "run-safe",
                        "status": "completed",
                    }
                },
                reason=None,
                audit_events=(
                    MissionAuditEvent(
                        "mission_execution_outcome",
                        "info",
                        {
                            "mission_id": "safe-mission",
                            "outcome": "completed",
                        },
                    ),
                ),
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
            execution_allowlist=C6A_EXECUTION_ALLOWLIST,
            set_test_led_executor=mutation,
            safe_mission_executor=mission,
        )
        return service, mission, mutation, status_calls, device_calls, audit

    def test_c6a_execution_allowlist_is_exact(self) -> None:
        self.assertEqual(
            C6A_EXECUTION_ALLOWLIST,
            (
                "system_status",
                "list_devices",
                "set_test_led",
                "run_safe_mission",
            ),
        )

    def test_room_mode_and_automation_remain_disabled(self) -> None:
        cases = (
            ("set_room_mode", {"mode": "study"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-automation"},
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                service, mission, mutation, status, devices, _ = (
                    self.integration(
                        response_with(
                            {"name": name, "arguments": arguments}
                        )
                    )
                )
                result = service.chat(REQUEST)
                self.assertEqual(
                    result.tool_results[0].reason,
                    "tool_not_enabled_in_c6a",
                )
                self.assertEqual(mission.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_brain_can_supply_only_mission_id(self) -> None:
        injected = (
            ("steps", []),
            ("node_id", "esp01"),
            ("target", "test_led"),
            ("action", "set"),
            ("payload", {"value": True}),
            ("topic", "alex/v1/nodes/esp01/command"),
        )
        for field, value in injected:
            with self.subTest(field=field):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Injected",
                    "tool_calls": [
                        {
                            "name": "run_safe_mission",
                            "arguments": {
                                "mission_id": "safe-mission",
                                field: value,
                            },
                        }
                    ],
                }
                service, mission, mutation, status, devices, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError) as raised:
                    service.chat(REQUEST)
                self.assertEqual(
                    raised.exception.code,
                    "invalid_brain_response",
                )
                self.assertEqual(mission.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_disabled_tool_mixed_batches_are_atomic(self) -> None:
        batches = (
            (
                {
                    "name": "run_safe_mission",
                    "arguments": {"mission_id": "safe-mission"},
                },
                {
                    "name": "run_safe_automation",
                    "arguments": {"automation_id": "safe-auto"},
                },
            ),
            (
                {
                    "name": "run_safe_mission",
                    "arguments": {"mission_id": "safe-mission"},
                },
                {"name": "set_room_mode", "arguments": {"mode": "away"}},
            ),
        )
        for calls in batches:
            with self.subTest(calls=calls):
                service, mission, mutation, status, devices, _ = (
                    self.integration(response_with(*calls))
                )
                result = service.chat(REQUEST)
                self.assertTrue(
                    all(
                        item.status == "rejected"
                        for item in result.tool_results
                    )
                )
                self.assertEqual(mission.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_unknown_bypass_tools_are_structurally_rejected(self) -> None:
        for name in (
            "mqtt_publish",
            "set_relay",
            "relay_1",
            "run_mission_raw",
        ):
            with self.subTest(name=name):
                malformed = {
                    "request_id": REQUEST.request_id,
                    "assistant_text": "Bypass",
                    "tool_calls": [{"name": name, "arguments": {}}],
                }
                service, mission, mutation, status, devices, _ = (
                    self.integration(malformed)
                )
                with self.assertRaises(BrainClientError):
                    service.chat(REQUEST)
                self.assertEqual(mission.ids, [])
                self.assertEqual(mutation.values, [])
                self.assertEqual(status, [])
                self.assertEqual(devices, [])

    def test_c4_reads_and_c5_direct_led_remain_enabled(self) -> None:
        service, mission, mutation, status, devices, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                {"name": "list_devices", "arguments": {}},
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                },
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["ok", "ok", "pending"],
        )
        self.assertEqual(status, [True])
        self.assertEqual(devices, [True])
        self.assertEqual(mutation.values, [True])
        self.assertEqual(mission.ids, [])

    def test_enabled_read_and_safe_mission_batch_executes_both(self) -> None:
        service, mission, mutation, status, devices, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                {
                    "name": "run_safe_mission",
                    "arguments": {"mission_id": "safe-mission"},
                },
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["ok", "completed"],
        )
        self.assertEqual(status, [True])
        self.assertEqual(mission.ids, ["safe-mission"])
        self.assertEqual(mutation.values, [])
        self.assertEqual(devices, [])

    def test_core_remains_fail_safe_when_brain_is_disabled(self) -> None:
        status_calls: list[bool] = []
        mission = MissionExecutorSpy(
            MissionOutcome(
                status="completed",
                result={"mission": {"status": "completed"}},
                reason=None,
                audit_events=(),
            )
        )
        service = CoreBrainIntegration(
            CoreBrainClient(CoreBrainConfig(enabled=False)),
            system_status_reader=lambda: (
                status_calls.append(True) or {"status": "ok"}
            ),
            device_list_reader=lambda: {"items": []},
            audit=lambda *_: None,
            execution_allowlist=C6A_EXECUTION_ALLOWLIST,
            set_test_led_executor=MutationSpy(),
            safe_mission_executor=mission,
        )
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "brain_disabled")
        self.assertEqual(status_calls, [])
        self.assertEqual(mission.ids, [])

    def test_assistant_claim_cannot_override_failed_or_running_mission(self) -> None:
        cases = (
            MissionOutcome(
                status="failed",
                result={
                    "mission": {
                        "mission_id": "run-failed",
                        "status": "failed",
                    }
                },
                reason="mission_execution_failed",
                audit_events=(),
            ),
            MissionOutcome(
                status="running",
                result={
                    "mission": {
                        "mission_id": "run-running",
                        "status": "running",
                    }
                },
                reason=None,
                audit_events=(),
            ),
        )
        for outcome in cases:
            with self.subTest(status=outcome.status):
                service, _, _, _, _, _ = self.integration(
                    response_with(
                        {
                            "name": "run_safe_mission",
                            "arguments": {
                                "mission_id": "safe-mission"
                            },
                        },
                        assistant_text="Mission đã hoàn tất thành công.",
                    ),
                    mission_outcome=outcome,
                )
                result = service.chat(REQUEST)
                self.assertEqual(
                    result.tool_results[0].status,
                    outcome.status,
                )

    def test_audit_is_correlated_bounded_and_secret_free(self) -> None:
        outcome = MissionOutcome(
            status="rejected",
            result={"mission_id": "denied-mission"},
            reason="mission_not_brain_allowed",
            audit_events=(
                MissionAuditEvent(
                    "mission_lookup",
                    "info",
                    {
                        "mission_id": "denied-mission",
                        "outcome": "found",
                    },
                ),
                MissionAuditEvent(
                    "mission_brain_allowed",
                    "warning",
                    {
                        "mission_id": "denied-mission",
                        "allowed": False,
                    },
                ),
            ),
        )
        service, _, _, _, _, audit = self.integration(
            response_with(
                {
                    "name": "run_safe_mission",
                    "arguments": {"mission_id": "denied-mission"},
                }
            ),
            mission_outcome=outcome,
        )
        service.chat(REQUEST)
        serialized = json.dumps(audit.records)
        self.assertIn("mission_brain_allowed", serialized)
        self.assertIn(REQUEST.request_id, serialized)
        for secret in (
            REQUEST.user_text,
            "ALEX_API_KEY",
            "ALEX_BRAIN_CLIENT_KEY",
            "MQTT_PASSWORD",
        ):
            self.assertNotIn(secret, serialized)

    def test_mission_path_has_no_direct_mqtt_or_second_executor(self) -> None:
        mission_source = inspect.getsource(
            __import__("alex_brain_missions")
        )
        self.assertNotIn("mqtt_client", mission_source)
        self.assertNotIn(".publish(", mission_source)
        self.assertIn("self._mission_executor.run(", mission_source)
        self.assertIn("gateway.authorize_batch(", mission_source)

    def test_relay_registry_remains_restricted(self) -> None:
        registry = CapabilityRegistry()
        for relay_id in range(1, 5):
            relay = registry.capability("esp01", f"relay_{relay_id}")
            self.assertFalse(relay.command_allowed)
            self.assertEqual(relay.verification_status, "restricted")
            self.assertEqual(relay.risk_level, "restricted")
            self.assertEqual(relay.allowed_modes, frozenset())


if __name__ == "__main__":
    unittest.main()
