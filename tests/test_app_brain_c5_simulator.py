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
from alex_brain_integration import (  # noqa: E402
    C5_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_mutations import (  # noqa: E402
    CommandGatewaySetTestLedExecutor,
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


class DeterministicProposalClient:
    """Test-only Brain stub; production has no fake inference fallback."""

    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        text = request.user_text.lower()
        if "xem" in text or "thiết bị" in text:
            calls = [{"name": "list_devices", "arguments": {}}]
        else:
            calls = [
                {
                    "name": "set_test_led",
                    "arguments": {"value": "tắt" not in text},
                }
            ]
        return BrainChatResponse.model_validate(
            {
                "request_id": request.request_id,
                "assistant_text": "Test-only deterministic proposal.",
                "tool_calls": calls,
            }
        )


class StaticToolClient:
    def __init__(self, name: str, arguments: dict[str, object]) -> None:
        self.name = name
        self.arguments = arguments

    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        return BrainChatResponse.model_validate(
            {
                "request_id": request.request_id,
                "assistant_text": "Disallowed proposal.",
                "tool_calls": [
                    {
                        "name": self.name,
                        "arguments": self.arguments,
                    }
                ],
            }
        )


class CoreBrainC5SimulatorEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "simulator.db")
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
        self.gateway = CommandGateway(
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

        registry = CapabilityRegistry()

        def device_reader() -> dict[str, object]:
            device = {
                **self.command_service.device(),
                **registry.get_node_status("esp01"),
            }
            return {"items": [device], "simulator": True}

        self.audit: list[dict[str, object]] = []
        self.integration = CoreBrainIntegration(
            DeterministicProposalClient(),
            system_status_reader=lambda: {
                "source": "simulated",
                "simulator": True,
            },
            device_list_reader=device_reader,
            audit=lambda stage, level, details: self.audit.append(
                {
                    "stage": stage,
                    "level": level,
                    "details": details,
                }
            ),
            execution_allowlist=C5_EXECUTION_ALLOWLIST,
            set_test_led_executor=CommandGatewaySetTestLedExecutor(
                self.gateway
            ),
        )
        self.client = AsgiTestClient(alex_app.app)

    def tearDown(self) -> None:
        self.simulator.stop()
        self.command_service.stop()
        self.temp.cleanup()

    def post(self, request_id: str, user_text: str):
        return self.client.post(
            "/api/v1/brain/chat",
            headers=CORE_AUTH,
            json_body={
                "request_id": request_id,
                "user_text": user_text,
            },
        )

    def assert_led_round_trip(
        self,
        *,
        value: bool,
        command_text: str,
        request_suffix: str,
    ) -> None:
        with patch.object(
            alex_app,
            "core_brain_integration",
            self.integration,
        ):
            command_response = self.post(
                f"req-c5-{request_suffix}",
                command_text,
            )
        self.assertEqual(command_response.status_code, 200)
        tool_result = command_response.json()["tool_results"][0]
        self.assertIn(tool_result["status"], {"pending", "confirmed"})
        command = tool_result["result"]["command"]
        command_id = command["command_id"]
        self.assertEqual(command["node_id"], "esp01")
        self.assertEqual(command["target"], "test_led")
        self.assertEqual(command["action"], "set")
        self.assertEqual(command["desired_state"], {"on": value})

        self.assertTrue(
            wait_for(
                lambda: (
                    self.gateway.command(command_id) or {}
                ).get("phase")
                == "confirmed"
            ),
            f"simulator command {command_id} did not confirm",
        )
        confirmed = self.gateway.command(command_id)
        self.assertEqual(confirmed["phase"], "confirmed")
        self.assertEqual(confirmed["reported_state"], {"on": value})
        self.assertIsNotNone(confirmed["acknowledged_at"])
        self.assertIsNotNone(confirmed["confirmed_at"])

        events = self.store.command_events(command_id)
        phases = [event["phase"] for event in events]
        for required in (
            "waiting_ack",
            "accepted",
            "waiting_reported_state",
            "confirmed",
        ):
            self.assertIn(required, phases)

        with patch.object(
            alex_app,
            "core_brain_integration",
            self.integration,
        ):
            devices_response = self.post(
                f"req-c5-devices-{request_suffix}",
                "Cho tôi xem các thiết bị.",
            )
        self.assertEqual(devices_response.status_code, 200)
        reported = devices_response.json()["tool_results"][0]["result"][
            "items"
        ][0]["reported_state"]["test_led"]
        self.assertEqual(reported, {"on": value})

    def test_core_endpoint_to_real_gateway_to_simulator_true_and_false(self) -> None:
        with patch.object(
            alex_app.mqtt_client,
            "publish",
        ) as production_mqtt_publish:
            self.assert_led_round_trip(
                value=True,
                command_text="Bật đèn test.",
                request_suffix="on",
            )
            self.assert_led_round_trip(
                value=False,
                command_text="Tắt đèn test.",
                request_suffix="off",
            )

        self.assertEqual(self.simulator.execution_count, 2)
        production_mqtt_publish.assert_not_called()
        stages = [record["stage"] for record in self.audit]
        self.assertGreaterEqual(stages.count("mutation_validated"), 2)
        self.assertGreaterEqual(stages.count("safety_decision"), 2)
        self.assertGreaterEqual(stages.count("mutation_result"), 2)

    def test_production_app_preserves_c5_tools_and_existing_gateway(self) -> None:
        self.assertEqual(
            alex_app.core_brain_integration._execution_allowlist[
                : len(C5_EXECUTION_ALLOWLIST)
            ],
            C5_EXECUTION_ALLOWLIST,
        )
        executor = alex_app.core_brain_integration._set_test_led_executor
        self.assertIsInstance(
            executor,
            CommandGatewaySetTestLedExecutor,
        )
        self.assertIs(executor._gateway, alex_app.command_gateway)

    def test_c5_disabled_tools_cannot_reach_app_mutation_services(self) -> None:
        cases = (
            ("set_room_mode", {"mode": "sleep"}),
            ("run_safe_mission", {"mission_id": "safe-study"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-check"},
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                integration = CoreBrainIntegration(
                    StaticToolClient(name, arguments),
                    system_status_reader=lambda: {},
                    device_list_reader=lambda: {"items": []},
                    audit=lambda stage, level, details: None,
                    execution_allowlist=C5_EXECUTION_ALLOWLIST,
                    set_test_led_executor=(
                        CommandGatewaySetTestLedExecutor(
                            alex_app.command_gateway
                        )
                    ),
                )
                original_mode = alex_app.device_state["mode"]
                with (
                    patch.object(
                        alex_app,
                        "core_brain_integration",
                        integration,
                    ),
                    patch.object(
                        alex_app.command_gateway,
                        "request",
                    ) as gateway,
                    patch.object(
                        alex_app.mission_executor,
                        "run",
                    ) as mission,
                    patch.object(
                        alex_app.automation_executor,
                        "evaluate",
                    ) as automation,
                    patch.object(
                        alex_app.mqtt_client,
                        "publish",
                    ) as mqtt_publish,
                ):
                    response = self.post(
                        f"req-c5-disabled-{name}",
                        f"Request {name}",
                    )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["tool_results"][0]["reason"],
                    "tool_not_enabled_in_c5",
                )
                gateway.assert_not_called()
                mission.assert_not_called()
                automation.assert_not_called()
                mqtt_publish.assert_not_called()
                self.assertEqual(
                    alex_app.device_state["mode"],
                    original_mode,
                )


if __name__ == "__main__":
    unittest.main()
