from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from alex_brain_integration import (
    C5_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_mutations import CommandGatewaySetTestLedExecutor
from alex_brain_tools import BrainChatRequest, BrainChatResponse
from alex_hardware import CommandService, RealtimeHub
from alex_safety import (
    Capability,
    CapabilityRegistry,
    CommandGateway,
    NodeCapabilities,
    SafetyPolicy,
)
from alex_store import AlexStore


REQUEST = BrainChatRequest(
    request_id="req-c5-safety",
    user_text="Bật đèn test.",
)


def response_with() -> BrainChatResponse:
    return BrainChatResponse.model_validate(
        {
            "request_id": REQUEST.request_id,
            "assistant_text": "Brain proposal",
            "tool_calls": [
                {
                    "name": "set_test_led",
                    "arguments": {"value": True},
                }
            ],
        }
    )


class StubClient:
    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        return response_with()


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


class CoreBrainC5SafetyTests(unittest.TestCase):
    def integration(
        self,
        gateway: CommandGateway,
        audit: AuditSpy | None = None,
    ) -> tuple[CoreBrainIntegration, AuditSpy]:
        audit_spy = audit or AuditSpy()
        return (
            CoreBrainIntegration(
                StubClient(),
                system_status_reader=lambda: {},
                device_list_reader=lambda: {"items": []},
                audit=audit_spy,
                execution_allowlist=C5_EXECUTION_ALLOWLIST,
                set_test_led_executor=(
                    CommandGatewaySetTestLedExecutor(gateway)
                ),
            ),
            audit_spy,
        )

    @staticmethod
    def command_runtime(
        directory: str,
        *,
        registry: CapabilityRegistry | None = None,
        publisher=None,
    ) -> tuple[CommandService, CommandGateway, list[tuple[object, ...]]]:
        store = AlexStore(Path(directory) / "commands.db")
        store.migrate()
        published: list[tuple[object, ...]] = []
        publish = publisher or (
            lambda *args: published.append(args) or True
        )
        service = CommandService(
            store,
            publish,
            RealtimeHub(),
            simulator_mode=True,
        )
        gateway = CommandGateway(
            SafetyPolicy(
                registry or CapabilityRegistry(),
                simulator_mode=True,
            ),
            service,
        )
        return service, gateway, published

    def test_publish_acceptance_alone_remains_pending_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service, gateway, published = self.command_runtime(temp)
            service.handle_heartbeat(
                {
                    "protocolVersion": 1,
                    "nodeId": "esp01",
                    "online": True,
                },
                "simulated",
            )
            outcome = CommandGatewaySetTestLedExecutor(gateway).execute(True)

        self.assertEqual(len(published), 1)
        self.assertEqual(outcome.status, "pending")
        self.assertEqual(
            outcome.result["command"]["phase"],
            "waiting_ack",
        )
        self.assertIsNone(outcome.result["command"]["confirmed_at"])

    def test_real_safety_denial_creates_no_command_or_publish(self) -> None:
        denied_led = Capability(
            node_id="esp01",
            capability_id="test_led",
            risk_level="safe",
            supported_actions=frozenset({"set"}),
            verification_status="basic_physical_validated",
            command_allowed=False,
            allowed_modes=frozenset({"simulator"}),
            restriction_reason="test_denial",
        )
        registry = CapabilityRegistry(
            {
                "esp01": NodeCapabilities(
                    "esp01",
                    "basic_physical_validated",
                    {"test_led": denied_led},
                )
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            _, gateway, published = self.command_runtime(
                temp,
                registry=registry,
            )
            service, audit = self.integration(gateway)
            result = service.chat(REQUEST)

        self.assertEqual(result.tool_results[0].status, "rejected")
        self.assertEqual(
            result.tool_results[0].reason,
            "safety_gateway_denied",
        )
        self.assertEqual(published, [])
        self.assertIn(
            "safety_decision",
            [record["stage"] for record in audit.records],
        )

    def test_offline_command_failure_keeps_authorized_safety_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, gateway, published = self.command_runtime(temp)
            service, audit = self.integration(gateway)
            result = service.chat(REQUEST)

        self.assertEqual(result.tool_results[0].status, "rejected")
        self.assertEqual(
            result.tool_results[0].reason,
            "device_unavailable",
        )
        self.assertEqual(published, [])
        safety = next(
            record for record in audit.records
            if record["stage"] == "safety_decision"
        )
        self.assertTrue(safety["details"]["allowed"])
        self.assertEqual(
            audit.records[-1]["details"]["failure_category"],
            "device_unavailable",
        )

    def test_relay_registry_restrictions_remain_exact(self) -> None:
        registry = CapabilityRegistry()
        for relay_id in range(1, 5):
            relay = registry.capability("esp01", f"relay_{relay_id}")
            self.assertIsNotNone(relay)
            self.assertFalse(relay.command_allowed)
            self.assertEqual(relay.verification_status, "restricted")
            self.assertEqual(relay.risk_level, "restricted")
            self.assertEqual(relay.allowed_modes, frozenset())
            self.assertEqual(
                relay.restriction_reason,
                "hardware_not_verified_and_no_safety_interlock",
            )

    def test_audit_covers_mapping_safety_outcome_and_contains_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service_runtime, gateway, _ = self.command_runtime(temp)
            service_runtime.handle_heartbeat(
                {
                    "protocolVersion": 1,
                    "nodeId": "esp01",
                    "online": True,
                },
                "simulated",
            )
            service, audit = self.integration(gateway)
            result = service.chat(REQUEST)

        command_id = result.tool_results[0].result["command"]["command_id"]
        stages = [record["stage"] for record in audit.records]
        for required in (
            "response_received",
            "mutation_validated",
            "fixed_mapping_selected",
            "safety_decision",
            "mutation_result",
        ):
            self.assertIn(required, stages)
        serialized = json.dumps(audit.records)
        for secret in (
            "ALEX_API_KEY",
            "ALEX_BRAIN_CLIENT_KEY",
            "MQTT_PASSWORD",
            REQUEST.user_text,
        ):
            self.assertNotIn(secret, serialized)
        self.assertIn(command_id, serialized)

    def test_brain_modules_have_no_direct_mqtt_execution_path(self) -> None:
        integration_source = inspect.getsource(
            __import__("alex_brain_integration")
        )
        mutation_source = inspect.getsource(
            __import__("alex_brain_mutations")
        )
        source = integration_source + mutation_source
        self.assertNotIn("mqtt_client", source)
        self.assertNotIn(".publish(", source)
        self.assertIn("self._gateway.request(", mutation_source)


if __name__ == "__main__":
    unittest.main()
