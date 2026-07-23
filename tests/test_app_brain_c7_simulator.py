from __future__ import annotations

import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_integration import (  # noqa: E402
    C7_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_room_mode import (  # noqa: E402
    AuthoritativeRoomModeExecutor,
)
from alex_brain_tools import BrainChatRequest, BrainChatResponse  # noqa: E402
from alex_hardware import CommandService, RealtimeHub  # noqa: E402
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


class RoomModeProposalClient:
    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        mode = "sleep" if "ngủ" in request.user_text.lower() else "study"
        return BrainChatResponse.model_validate(
            {
                "request_id": request.request_id,
                "assistant_text": (
                    "Đã đổi mode và xử lý toàn bộ thiết bị theo model."
                ),
                "tool_calls": [
                    {
                        "name": "set_room_mode",
                        "arguments": {"mode": mode},
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


class CoreBrainC7SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_device_state = deepcopy(alex_app.device_state)
        with alex_app.state_lock:
            alex_app.device_state["mode"] = "home"

        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "c7.db")
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
        self.assertEqual(
            self.command_service.device()["reported_state"]["test_led"],
            {"on": False},
        )
        self.audit: list[dict[str, object]] = []
        self.integration = CoreBrainIntegration(
            RoomModeProposalClient(),
            system_status_reader=lambda: {"source": "core"},
            device_list_reader=lambda: {"items": []},
            audit=lambda stage, level, details: self.audit.append(
                {
                    "stage": stage,
                    "level": level,
                    "details": details,
                }
            ),
            execution_allowlist=C7_EXECUTION_ALLOWLIST,
            room_mode_executor=AuthoritativeRoomModeExecutor(
                alex_app._set_authoritative_room_mode
            ),
        )
        self.client = AsgiTestClient(alex_app.app)

    def tearDown(self) -> None:
        self.simulator.stop()
        self.command_service.stop()
        self.temp.cleanup()
        with alex_app.state_lock:
            alex_app.device_state.clear()
            alex_app.device_state.update(self.original_device_state)

    def post(self, request_id: str, text: str):
        return self.client.post(
            "/api/v1/brain/chat",
            headers=CORE_AUTH,
            json_body={"request_id": request_id, "user_text": text},
        )

    def test_study_then_sleep_change_only_authoritative_logical_mode(self) -> None:
        original_relays = deepcopy(alex_app.device_state["relays"])
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
            patch.object(
                alex_app.command_gateway,
                "request",
            ) as production_gateway,
            patch.object(
                alex_app.command_service,
                "_create_test_led_command",
            ) as production_command_service,
            patch.object(
                alex_app.mission_executor,
                "run",
            ) as production_mission,
            patch.object(
                alex_app.automation_executor,
                "evaluate",
            ) as production_automation,
        ):
            study = self.post(
                "req-c7-study",
                "Chuyển sang chế độ học.",
            )
            sleep = self.post(
                "req-c7-sleep",
                "Chuyển sang chế độ ngủ.",
            )

        self.assertEqual(study.status_code, 200)
        study_result = study.json()["tool_results"][0]
        self.assertEqual(study_result["status"], "ok")
        self.assertEqual(study_result["result"]["mode"], "study")
        self.assertEqual(study_result["result"]["physical_actions"], [])

        self.assertEqual(sleep.status_code, 200)
        sleep_result = sleep.json()["tool_results"][0]
        self.assertEqual(sleep_result["status"], "ok")
        self.assertEqual(sleep_result["result"]["mode"], "sleep")
        self.assertEqual(sleep_result["result"]["physical_actions"], [])

        self.assertEqual(alex_app.device_state["mode"], "sleep")
        self.assertEqual(alex_app.device_state["relays"], original_relays)
        self.assertEqual(
            self.command_service.device()["reported_state"]["test_led"],
            {"on": False},
        )
        self.assertEqual(self.gateway.request_count, 0)
        self.assertEqual(self.simulator.execution_count, 0)
        production_mqtt.assert_not_called()
        production_gateway.assert_not_called()
        production_command_service.assert_not_called()
        production_mission.assert_not_called()
        production_automation.assert_not_called()

    def test_production_app_reuses_existing_room_mode_authority(self) -> None:
        self.assertEqual(
            alex_app.core_brain_integration._execution_allowlist,
            C7_EXECUTION_ALLOWLIST,
        )
        adapter = alex_app.core_brain_integration._room_mode_executor
        self.assertIsInstance(adapter, AuthoritativeRoomModeExecutor)
        self.assertIs(
            adapter._setter,
            alex_app._set_authoritative_room_mode,
        )


if __name__ == "__main__":
    unittest.main()
