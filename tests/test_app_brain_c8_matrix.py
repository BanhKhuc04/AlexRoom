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
from alex_brain_automations import (  # noqa: E402
    StoredSafeAutomationExecutor,
)
from alex_brain_integration import (  # noqa: E402
    C7_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_missions import StoredSafeMissionExecutor  # noqa: E402
from alex_brain_mutations import (  # noqa: E402
    CommandGatewaySetTestLedExecutor,
)
from alex_brain_room_mode import (  # noqa: E402
    AuthoritativeRoomModeExecutor,
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


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class MatrixProposalClient:
    CALLS = {
        "status": ("system_status", {}),
        "devices": ("list_devices", {}),
        "led-on": ("set_test_led", {"value": True}),
        "led-off": ("set_test_led", {"value": False}),
        "mode-study": ("set_room_mode", {"mode": "study"}),
        "mode-sleep": ("set_room_mode", {"mode": "sleep"}),
        "mission-safe": (
            "run_safe_mission",
            {"mission_id": "c8-safe-mission"},
        ),
        "mission-unsafe": (
            "run_safe_mission",
            {"mission_id": "c8-unsafe-mission"},
        ),
        "automation-safe": (
            "run_safe_automation",
            {"automation_id": "c8-safe-automation"},
        ),
        "automation-unsafe": (
            "run_safe_automation",
            {"automation_id": "c8-unsafe-automation"},
        ),
    }

    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        name, arguments = self.CALLS[request.user_text]
        return BrainChatResponse.model_validate(
            {
                "request_id": request.request_id,
                "assistant_text": "Structured proposal only.",
                "tool_calls": [
                    {"name": name, "arguments": arguments}
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


class Phase08SimulatorMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "c8.db")
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
        self.registry = CapabilityRegistry()
        self.gateway = CountingCommandGateway(
            SafetyPolicy(self.registry, simulator_mode=True),
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
        self._put_records()
        self.mode = {"value": "home"}

        def set_mode(mode):
            previous = self.mode["value"]
            self.mode["value"] = mode
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

        self.audit: list[dict[str, object]] = []
        self.integration = CoreBrainIntegration(
            MatrixProposalClient(),
            system_status_reader=lambda: {
                "source": "simulated",
                "node": self.registry.get_node_status("esp01"),
            },
            device_list_reader=lambda: {
                "items": [
                    {
                        **self.command_service.device(),
                        **self.registry.get_node_status("esp01"),
                    }
                ],
                "simulator": True,
            },
            audit=lambda stage, level, details: self.audit.append(
                {
                    "stage": stage,
                    "level": level,
                    "details": details,
                }
            ),
            execution_allowlist=C7_EXECUTION_ALLOWLIST,
            set_test_led_executor=CommandGatewaySetTestLedExecutor(
                self.gateway
            ),
            safe_mission_executor=StoredSafeMissionExecutor(
                self.store,
                self.mission_executor,
                self.gateway,
            ),
            safe_automation_executor=StoredSafeAutomationExecutor(
                self.store,
                self.automation_executor,
                self.gateway,
            ),
            room_mode_executor=AuthoritativeRoomModeExecutor(set_mode),
        )

    def tearDown(self) -> None:
        self.simulator.stop()
        self.command_service.stop()
        self.temp.cleanup()

    def _put_records(self) -> None:
        safe_steps = [
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
        ]
        unsafe_steps = [
            safe_steps[0],
            {
                "node_id": "esp01",
                "target": "relay_1",
                "action": "on",
            },
        ]
        self.store.put_record(
            "missions",
            "c8-safe-mission",
            {
                "brain_allowed": True,
                "steps": safe_steps,
                "source": "simulated",
            },
        )
        self.store.put_record(
            "missions",
            "c8-unsafe-mission",
            {
                "brain_allowed": True,
                "steps": unsafe_steps,
                "source": "simulated",
            },
        )
        for record_id, actions in (
            ("c8-safe-automation", safe_steps),
            ("c8-unsafe-automation", unsafe_steps),
        ):
            self.store.put_record(
                "automations",
                record_id,
                {
                    "brain_allowed": True,
                    "enabled": True,
                    "trigger": {"type": "manual"},
                    "conditions": [],
                    "actions": actions,
                    "source": "simulated",
                },
            )

    def call(self, token: str):
        return self.integration.chat(
            BrainChatRequest(
                request_id=f"req-c8-{token}",
                user_text=token,
            )
        ).tool_results[0]

    def test_complete_six_tool_simulator_matrix(self) -> None:
        with patch.object(
            alex_app.mqtt_client,
            "publish",
        ) as production_mqtt:
            self.assertEqual(self.call("status").status, "ok")
            devices = self.call("devices")
            self.assertEqual(devices.status, "ok")
            self.assertEqual(len(devices.result["items"]), 1)

            led_on = self.call("led-on")
            self.assertIn(led_on.status, {"pending", "confirmed"})
            self.assertTrue(
                wait_for(
                    lambda: self.command_service.device()[
                        "reported_state"
                    ]["test_led"]["on"]
                    is True
                )
            )
            led_off = self.call("led-off")
            self.assertIn(led_off.status, {"pending", "confirmed"})
            self.assertTrue(
                wait_for(
                    lambda: self.command_service.device()[
                        "reported_state"
                    ]["test_led"]["on"]
                    is False
                )
            )

            self.assertEqual(self.call("mode-study").status, "ok")
            self.assertEqual(self.mode["value"], "study")
            self.assertEqual(self.call("mode-sleep").status, "ok")
            self.assertEqual(self.mode["value"], "sleep")

            safe_mission = self.call("mission-safe")
            self.assertEqual(safe_mission.status, "completed")
            before_unsafe_mission = self.gateway.request_count
            unsafe_mission = self.call("mission-unsafe")
            self.assertEqual(unsafe_mission.status, "rejected")
            self.assertEqual(
                unsafe_mission.reason,
                "mission_preflight_failed",
            )
            self.assertEqual(
                self.gateway.request_count,
                before_unsafe_mission,
            )

            safe_automation = self.call("automation-safe")
            self.assertEqual(safe_automation.status, "completed")
            before_unsafe_automation = self.gateway.request_count
            unsafe_automation = self.call("automation-unsafe")
            self.assertEqual(unsafe_automation.status, "rejected")
            self.assertEqual(
                unsafe_automation.reason,
                "automation_preflight_failed",
            )
            self.assertEqual(
                self.gateway.request_count,
                before_unsafe_automation,
            )

        self.assertEqual(self.gateway.request_count, 6)
        self.assertEqual(self.simulator.execution_count, 6)
        self.assertEqual(len(self.store.records("mission_runs")), 2)
        self.assertEqual(
            self.command_service.device()["reported_state"]["test_led"],
            {"on": False},
        )
        production_mqtt.assert_not_called()
        for relay_id in range(1, 5):
            relay = self.registry.capability(
                "esp01",
                f"relay_{relay_id}",
            )
            self.assertFalse(relay.command_allowed)
            self.assertEqual(relay.verification_status, "restricted")


if __name__ == "__main__":
    unittest.main()
