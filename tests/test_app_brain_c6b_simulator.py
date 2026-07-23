from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_automations import (  # noqa: E402
    StoredSafeAutomationExecutor,
)
from alex_brain_integration import (  # noqa: E402
    C6B_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_tools import BrainChatRequest, BrainChatResponse  # noqa: E402
from alex_hardware import CommandService, RealtimeHub  # noqa: E402
from alex_orchestration import AutomationExecutor, MissionExecutor  # noqa: E402
from alex_safety import (  # noqa: E402
    CapabilityRegistry,
    CommandGateway,
    SafetyPolicy,
)
from alex_simulator import Esp01Simulator  # noqa: E402
from alex_store import AlexStore  # noqa: E402


CORE_AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class AutomationProposalClient:
    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        automation_id = (
            "unsafe-relay-automation"
            if "unsafe" in request.user_text.lower()
            else "safe-led-automation"
        )
        return BrainChatResponse.model_validate(
            {
                "request_id": request.request_id,
                "assistant_text": (
                    "Automation đã chạy xong theo model."
                ),
                "tool_calls": [
                    {
                        "name": "run_safe_automation",
                        "arguments": {
                            "automation_id": automation_id
                        },
                    }
                ],
            }
        )


class CountingCommandGateway(CommandGateway):
    def __init__(self, policy, command_service) -> None:
        super().__init__(policy, command_service)
        self.request_count = 0

    def request(self, **kwargs):
        self.request_count += 1
        return super().request(**kwargs)


class CoreBrainC6BSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "c6b.db")
        self.store.migrate()
        self.hub = RealtimeHub()
        self.command_service = CommandService(
            self.store,
            lambda *args: False,
            self.hub,
            ack_timeout=0.2,
            reported_timeout=0.2,
            max_retries=1,
            simulator_mode=True,
        )
        self.gateway = CountingCommandGateway(
            SafetyPolicy(CapabilityRegistry(), simulator_mode=True),
            self.command_service,
        )
        self.simulator = Esp01Simulator(
            self.command_service.handle_heartbeat,
            self.command_service.handle_ack,
            self.command_service.handle_reported,
            scenario="normal",
        )
        self.command_service.publisher = self.simulator.publish
        self.command_service.start()
        self.simulator.start()
        self.assertTrue(
            wait_for(
                lambda: self.command_service.device()["connection"]
                == "online"
            )
        )
        self.mission_executor = MissionExecutor(
            self.store,
            self.gateway,
            timeout=1.0,
        )
        self.automation_executor = AutomationExecutor(
            self.store,
            self.mission_executor,
            self.gateway,
        )
        self.store.put_record(
            "automations",
            "safe-led-automation",
            {
                "name": "Local safe LED automation",
                "brain_allowed": True,
                "enabled": True,
                "trigger": {"type": "manual"},
                "conditions": [],
                "source": "simulated",
                "actions": [
                    {
                        "node_id": "esp01",
                        "target": "test_led",
                        "action": "set",
                        "value": True,
                    },
                    {
                        "node_id": "esp01",
                        "target": "test_led",
                        "action": "set",
                        "value": False,
                    },
                ],
            },
        )
        self.store.put_record(
            "automations",
            "unsafe-relay-automation",
            {
                "name": "Local unsafe relay automation",
                "brain_allowed": True,
                "enabled": True,
                "trigger": {"type": "manual"},
                "conditions": [],
                "source": "simulated",
                "actions": [
                    {
                        "node_id": "esp01",
                        "target": "test_led",
                        "action": "set",
                        "value": True,
                    },
                    {
                        "node_id": "esp01",
                        "target": "relay_1",
                        "action": "on",
                    },
                ],
            },
        )
        self.audit: list[dict[str, object]] = []
        self.integration = CoreBrainIntegration(
            AutomationProposalClient(),
            system_status_reader=lambda: {
                "source": "simulated",
                "simulator": True,
            },
            device_list_reader=lambda: {"items": [], "simulator": True},
            audit=lambda stage, level, details: self.audit.append(
                {
                    "stage": stage,
                    "level": level,
                    "details": details,
                }
            ),
            execution_allowlist=C6B_EXECUTION_ALLOWLIST,
            safe_automation_executor=StoredSafeAutomationExecutor(
                self.store,
                self.automation_executor,
                self.gateway,
            ),
        )
        self.client = AsgiTestClient(alex_app.app)

    def tearDown(self) -> None:
        self.simulator.stop()
        self.command_service.stop()
        self.temp.cleanup()

    def post(self, request_id: str, text: str):
        return self.client.post(
            "/api/v1/brain/chat",
            headers=CORE_AUTH,
            json_body={"request_id": request_id, "user_text": text},
        )

    def test_safe_automation_uses_real_existing_orchestration_stack(self) -> None:
        with (
            patch.object(
                alex_app,
                "core_brain_integration",
                self.integration,
            ),
            patch.object(
                alex_app.mqtt_client,
                "publish",
            ) as production_mqtt,
        ):
            response = self.post(
                "req-c6b-safe",
                "Chạy automation test đèn an toàn.",
            )

        self.assertEqual(response.status_code, 200)
        tool_result = response.json()["tool_results"][0]
        self.assertEqual(tool_result["status"], "completed")
        evaluation = tool_result["result"]["automation"]
        self.assertTrue(evaluation["matched"])
        self.assertEqual(evaluation["mission"]["status"], "completed")
        self.assertEqual(
            [
                step["status"]
                for step in evaluation["mission"]["steps"]
            ],
            ["confirmed", "confirmed"],
        )
        self.assertEqual(self.gateway.request_count, 2)
        self.assertEqual(self.simulator.execution_count, 2)
        self.assertEqual(
            self.command_service.device()["reported_state"]["test_led"],
            {"on": False},
        )
        self.assertEqual(len(self.store.records("mission_runs")), 1)
        updated = self.store.get_record(
            "automations",
            "safe-led-automation",
        )
        self.assertIsNotNone(updated.get("lastEvaluation"))
        production_mqtt.assert_not_called()
        stages = [record["stage"] for record in self.audit]
        self.assertIn("automation_resolution", stages)
        self.assertIn("automation_preflight", stages)
        self.assertIn("automation_execution_start", stages)
        self.assertIn("automation_execution_outcome", stages)

    def test_unsafe_automation_rejects_before_any_side_effect(self) -> None:
        initial = self.command_service.device()["reported_state"]["test_led"]
        with (
            patch.object(
                alex_app,
                "core_brain_integration",
                self.integration,
            ),
            patch.object(
                alex_app.mqtt_client,
                "publish",
            ) as production_mqtt,
        ):
            response = self.post(
                "req-c6b-unsafe",
                "Chạy unsafe automation có relay.",
            )

        self.assertEqual(response.status_code, 200)
        tool_result = response.json()["tool_results"][0]
        self.assertEqual(tool_result["status"], "rejected")
        self.assertEqual(
            tool_result["reason"],
            "automation_preflight_failed",
        )
        preflight = tool_result["result"]["preflight"]
        self.assertEqual(preflight["denied_step_index"], 1)
        self.assertEqual(preflight["denied_capability"], "relay_1")
        self.assertEqual(self.gateway.request_count, 0)
        self.assertEqual(self.simulator.execution_count, 0)
        self.assertEqual(
            self.command_service.device()["reported_state"]["test_led"],
            initial,
        )
        self.assertEqual(self.store.records("mission_runs"), [])
        updated = self.store.get_record(
            "automations",
            "unsafe-relay-automation",
        )
        self.assertNotIn("lastEvaluation", updated)
        production_mqtt.assert_not_called()

    def test_production_app_preserves_c6b_automation_wiring(self) -> None:
        self.assertEqual(
            tuple(
                tool
                for tool in alex_app.core_brain_integration._execution_allowlist
                if tool != "set_room_mode"
            ),
            C6B_EXECUTION_ALLOWLIST,
        )
        adapter = alex_app.core_brain_integration._safe_automation_executor
        self.assertIsInstance(adapter, StoredSafeAutomationExecutor)
        self.assertIs(
            adapter._automation_executor,
            alex_app.automation_executor,
        )
        self.assertIs(adapter._gateway, alex_app.command_gateway)
        self.assertIs(adapter._store, alex_app.store)


if __name__ == "__main__":
    unittest.main()
