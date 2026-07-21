from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["MQTT_PASSWORD"] = "unit-test-password"
os.environ["ALEX_API_KEY"] = "unit-test-api-key"
os.environ["ALEX_SIMULATOR"] = "0"
os.environ["ALEX_DATABASE_PATH"] = "data/unit-test-app.db"

import app as alex_app  # noqa: E402
from alex_safety import Capability, CapabilityRegistry, NodeCapabilities  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class AppSafetyBoundaryTests(unittest.TestCase):
    def assert_locked(self, callback) -> dict:
        with self.assertRaises(HTTPException) as raised:
            callback()
        self.assertEqual(raised.exception.status_code, 423)
        return raised.exception.detail

    def test_valid_api_key_does_not_bypass_relay_lockdown(self) -> None:
        alex_app.require_api_key(alex_app.ALEX_API_KEY)
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            detail = self.assert_locked(lambda: alex_app.control_relay(1, "ON", None))
        self.assertEqual(detail["reason"], "restricted_capability")
        mqtt_publish.assert_not_called()

    def test_legacy_relay_on_and_off_have_zero_mqtt_publish(self) -> None:
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            for action in ("ON", "OFF"):
                detail = self.assert_locked(lambda action=action: alex_app.control_relay(1, action, None))
                self.assertEqual(detail["risk_level"], "restricted")
        mqtt_publish.assert_not_called()

    def test_relays_all_on_and_off_have_zero_mqtt_publish(self) -> None:
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            for action in ("ON", "OFF"):
                detail = self.assert_locked(lambda action=action: alex_app.control_all_relays(action, None))
                self.assertEqual(detail["reason"], "batch_contains_denied_capability")
                self.assertEqual(len(detail["decisions"]), 4)
        mqtt_publish.assert_not_called()

    def test_sleep_and_away_only_update_logical_mode(self) -> None:
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            for mode in ("sleep", "away"):
                response = alex_app.set_mode(alex_app.ModeRequest(mode=mode), None)
                self.assertEqual(response["mode"], mode)
                self.assertTrue(response["logical_mode_updated"])
                self.assertEqual(response["physical_actions"], [])
                self.assertEqual(response["physical_result"], "not_requested_restricted_capabilities")
        mqtt_publish.assert_not_called()

    def test_v1_safe_risk_claim_cannot_bypass_relay_policy(self) -> None:
        request = alex_app.V1CommandRequest(
            node_id="esp01",
            target="relay_1",
            action="on",
            payload={"value": True},
            risk_level="safe",
            origin="test",
        )
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            detail = self.assert_locked(lambda: alex_app.v1_command(request, None))
        self.assertEqual(detail["risk_level"], "restricted")
        mqtt_publish.assert_not_called()

    def test_command_transport_rejects_legacy_relay_topic(self) -> None:
        legacy_topic = "alex/device/esp01/switch/relay_1/command"
        with patch.object(alex_app.mqtt_client, "publish") as mqtt_publish:
            accepted = alex_app._publish_v1_command(legacy_topic, "ON", 0, False)
        self.assertFalse(accepted)
        mqtt_publish.assert_not_called()

    def test_denial_audit_contains_structured_safety_truth(self) -> None:
        with patch.object(alex_app, "add_event") as add_event:
            self.assert_locked(lambda: alex_app.control_relay(3, "OFF", None))
        details = add_event.call_args.args[3]
        self.assertEqual(
            {key: details[key] for key in ("node", "capability", "action", "status", "risk", "reason")},
            {
                "node": "esp01", "capability": "relay_3", "action": "off",
                "status": "restricted", "risk": "restricted", "reason": "restricted_capability",
            },
        )

    def test_status_and_device_apis_derive_truth_from_registry_fixture(self) -> None:
        led = Capability(
            node_id="esp01", capability_id="test_led", risk_level="safe",
            supported_actions=frozenset({"set"}), verification_status="hardware_verified",
            command_allowed=True, allowed_modes=frozenset({"hardware"}),
        )
        fixture = CapabilityRegistry({
            "esp01": NodeCapabilities("esp01", "software_verified", {"test_led": led}),
        })
        with (
            patch.object(alex_app, "capability_registry", fixture),
            patch.object(alex_app.store, "health", return_value={"status": "ok"}),
        ):
            status = alex_app.v1_status()
            capabilities = alex_app.v1_safety_capabilities()
            devices = alex_app.v1_devices()
            legacy = alex_app.get_esp01()

        for node in (status["node"], capabilities["nodes"]["esp01"], devices["items"][0], legacy):
            self.assertEqual(node["verification_status"], "software_verified")
            self.assertFalse(node["hardware_verified"])
            self.assertEqual(node["capabilities"]["test_led"]["verification_status"], "hardware_verified")

    def test_command_response_exposes_capability_truth_without_global_claim(self) -> None:
        command = {"command_id": "cmd-fixture", "node_id": "esp01", "target": "test_led"}
        response = alex_app._with_command_verification(command)
        self.assertNotIn("hardware_verified", response)
        self.assertFalse(response["verification"]["node"]["hardware_verified"])
        self.assertEqual(
            response["verification"]["capability"]["verification_status"],
            "basic_physical_validated",
        )

    def test_runtime_services_do_not_duplicate_registry_verification_values(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app.py").read_text(encoding="utf-8")
        hardware_source = (root / "alex_hardware.py").read_text(encoding="utf-8")
        self.assertNotIn('"hardware_verified": False', app_source)
        self.assertNotIn('"hardware_verified": False', hardware_source)
        self.assertNotIn('"basic_physical_validation": True', hardware_source)


if __name__ == "__main__":
    unittest.main()
