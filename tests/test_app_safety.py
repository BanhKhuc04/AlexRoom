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

        # v1/devices now returns a single canonical record — no duplicate.
        self.assertEqual(len(devices["items"]), 1, "v1/devices must expose exactly one ESP01 record")
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


class HealthConsistencyTests(unittest.TestCase):
    """Regression tests for the broker-restart health/device truth-consistency bug.

    Root cause: /health previously read device_state["availability"] (legacy MQTT
    availability topic), while /api/v1/devices read command_service.device()["connection"]
    (V1 heartbeat).  After a broker restart the V1 heartbeat resumes before the legacy
    availability topic is re-published, so the two sources disagreed.  Both endpoints
    now derive connectivity truth exclusively from command_service.device().
    """

    def setUp(self) -> None:
        # Reset the command_service V1 device to a known state before each test
        # so tests don't bleed state into each other through the module singleton.
        # Also mock store.put_device so tests don't require a migrated SQLite DB
        # (the test module is imported before store.migrate() runs in production).
        import unittest.mock as mock
        self._store_patcher = mock.patch.object(alex_app.command_service.store, "put_device")
        self._store_patcher.start()
        with alex_app.command_service._lock:
            alex_app.command_service._device = alex_app.command_service._default_device()
        # Also reset the legacy device_state to a neutral value.
        with alex_app.state_lock:
            alex_app.device_state["availability"] = "unknown"

    def tearDown(self) -> None:
        self._store_patcher.stop()

    def _make_heartbeat(self, online: bool = True) -> dict:
        return {
            "protocolVersion": 1,
            "nodeId": "esp01",
            "firmware": "0.4.0",
            "ip": "192.168.0.42",
            "rssi": -38,
            "online": online,
        }

    def test_v1_heartbeat_sets_esp01_online(self) -> None:
        """handle_heartbeat(online=True) must set connection='online' in the V1 device."""
        alex_app.command_service.handle_heartbeat(self._make_heartbeat(online=True), "mqtt")
        device = alex_app.command_service.device()
        self.assertEqual(device["connection"], "online")

    def test_health_reports_online_after_v1_heartbeat(self) -> None:
        """/health must report device='online' after a V1 heartbeat arrives."""
        alex_app.command_service.handle_heartbeat(self._make_heartbeat(online=True), "mqtt")
        result = alex_app.health()
        self.assertEqual(result["device"], "online")

    def test_stale_legacy_availability_cannot_force_health_offline(self) -> None:
        """Even if legacy device_state['availability'] is 'offline', /health must reflect
        the authoritative V1 heartbeat connection state, not the legacy value."""
        alex_app.command_service.handle_heartbeat(self._make_heartbeat(online=True), "mqtt")
        # Deliberately corrupt the legacy state to simulate the stale scenario.
        with alex_app.state_lock:
            alex_app.device_state["availability"] = "offline"
        result = alex_app.health()
        self.assertEqual(
            result["device"], "online",
            "/health must not be dragged offline by stale legacy availability state",
        )

    def test_v1_devices_exposes_exactly_one_esp01_record(self) -> None:
        """/api/v1/devices must return exactly one ESP01 record after the fix.
        Two conflicting records with different connection values are not acceptable.
        """
        devices = alex_app.v1_devices()
        self.assertEqual(
            len(devices["items"]), 1,
            f"Expected 1 canonical ESP01 record, got {len(devices['items'])}",
        )

    def test_broker_reconnect_and_resumed_heartbeat_restores_online(self) -> None:
        """Simulate broker restart: mark offline via LWT, then receive a fresh heartbeat.
        After the heartbeat, both /health and /api/v1/devices must show 'online'.
        """
        # 1. LWT fires — device goes offline.
        alex_app.command_service.mark_offline("mqtt")
        self.assertEqual(alex_app.command_service.device()["connection"], "offline")

        # 2. ESP01 resumes heartbeat after broker restart.
        alex_app.command_service.handle_heartbeat(self._make_heartbeat(online=True), "mqtt")

        # 3. /health must now be online.
        self.assertEqual(alex_app.health()["device"], "online")

        # 4. /api/v1/devices must show online for the single canonical record.
        devices = alex_app.v1_devices()
        self.assertEqual(devices["items"][0]["connection"], "online")

    def test_verification_truth_unchanged_after_heartbeat(self) -> None:
        """Online connectivity from V1 heartbeat must NOT affect verification truth.
        esp01.hardware_verified must remain False; relay_1..4 must stay restricted.
        """
        alex_app.command_service.handle_heartbeat(self._make_heartbeat(online=True), "mqtt")
        devices = alex_app.v1_devices()
        node = devices["items"][0]
        # Connection is online but verification is independent.
        self.assertEqual(node["connection"], "online")
        self.assertFalse(node["hardware_verified"],
                         "ONLINE must not imply hardware_verified")
        self.assertEqual(node["verification_status"], "basic_physical_validated")
        caps = node["capabilities"]
        for relay in ("relay_1", "relay_2", "relay_3", "relay_4"):
            self.assertEqual(caps[relay]["verification_status"], "restricted",
                             f"{relay} must remain restricted after heartbeat")
            self.assertFalse(caps[relay]["command_allowed"],
                             f"{relay} command_allowed must remain False after heartbeat")


if __name__ == "__main__":
    unittest.main()
