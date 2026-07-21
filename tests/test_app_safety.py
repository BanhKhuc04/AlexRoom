from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["MQTT_PASSWORD"] = "unit-test-password"
os.environ["ALEX_API_KEY"] = "unit-test-api-key"
os.environ["ALEX_SIMULATOR"] = "0"
os.environ["ALEX_DATABASE_PATH"] = "data/unit-test-app.db"

import app as alex_app  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
