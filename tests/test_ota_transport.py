import unittest
from unittest.mock import MagicMock, patch
import json
import paho.mqtt.client as mqtt

from app import _publish_v1_command, _publish_ota_command, mqtt_connected, mqtt_client, simulator
from alex_hardware import COMMAND_TOPIC, OTA_COMMAND_TOPIC, OTA_STATUS_TOPIC

class TestOtaTransport(unittest.TestCase):
    def setUp(self):
        # Reset globals for tests
        mqtt_connected.set()
        self.original_publish = mqtt_client.publish
        self.mock_publish = MagicMock()
        mqtt_client.publish = self.mock_publish
        
        # We need simulator to be None to test real MQTT path
        self.original_simulator = simulator
        import app
        app.simulator = None
        
        # Mock result for success
        self.mock_result = MagicMock()
        self.mock_result.rc = mqtt.MQTT_ERR_SUCCESS
        self.mock_publish.return_value = self.mock_result

    def tearDown(self):
        mqtt_client.publish = self.original_publish
        import app
        app.simulator = self.original_simulator

    def test_1_publish_v1_command_rejects_ota_topic(self):
        result = _publish_v1_command(OTA_COMMAND_TOPIC, "payload", 1, False)
        self.assertFalse(result)
        self.mock_publish.assert_not_called()

    def test_2_and_3_publish_ota_command_accepts_ota_only(self):
        # 2. accepts only OTA_COMMAND_TOPIC
        result = _publish_ota_command(OTA_COMMAND_TOPIC, '{"a": 1}', 1, False)
        self.assertTrue(result)
        self.mock_publish.assert_called_once()
        
        self.mock_publish.reset_mock()
        
        # 3. rejects COMMAND_TOPIC
        result = _publish_ota_command(COMMAND_TOPIC, "payload", 1, False)
        self.assertFalse(result)
        self.mock_publish.assert_not_called()

    def test_4_arbitrary_topics_rejected(self):
        result_v1 = _publish_v1_command("random/topic", "payload", 1, False)
        self.assertFalse(result_v1)
        
        result_ota = _publish_ota_command("random/topic", "payload", 1, False)
        self.assertFalse(result_ota)
        
        self.mock_publish.assert_not_called()

    def test_5_to_9_ota_dict_payload_serialized_correctly(self):
        payload_dict = {
            "protocolVersion": 1,
            "commandId": "op-123",
            "targetVersion": "1.0.2",
            "url": "http://127.0.0.1/bin",
            "sha256": "abcdef",
            "size": 1024
        }
        
        result = _publish_ota_command(OTA_COMMAND_TOPIC, payload_dict, 1, False)
        self.assertTrue(result)
        
        self.mock_publish.assert_called_once()
        called_topic, called_payload = self.mock_publish.call_args[0]
        kwargs = self.mock_publish.call_args[1]
        
        self.assertEqual(called_topic, OTA_COMMAND_TOPIC)
        
        # 8. QoS = 1
        self.assertEqual(kwargs.get("qos"), 1)
        
        # 9. retain = false
        self.assertEqual(kwargs.get("retain"), False)
        
        # 5. OTA dict payload is JSON serialized correctly
        self.assertIsInstance(called_payload, str)
        parsed = json.loads(called_payload)
        
        # 6. published payload contains protocolVersion == 1
        self.assertEqual(parsed["protocolVersion"], 1)
        
        # 7. targetVersion / commandId / URL / sha256 / size preserved
        self.assertEqual(parsed["commandId"], "op-123")
        self.assertEqual(parsed["targetVersion"], "1.0.2")
        self.assertEqual(parsed["url"], "http://127.0.0.1/bin")
        self.assertEqual(parsed["sha256"], "abcdef")
        self.assertEqual(parsed["size"], 1024)

    def test_10_disconnected_mqtt_returns_false(self):
        mqtt_connected.clear()
        result = _publish_ota_command(OTA_COMMAND_TOPIC, "{}", 1, False)
        self.assertFalse(result)
        self.mock_publish.assert_not_called()

    def test_11_failed_mqtt_publish_is_not_success(self):
        self.mock_result.rc = mqtt.MQTT_ERR_NO_CONN
        result = _publish_ota_command(OTA_COMMAND_TOPIC, "{}", 1, False)
        self.assertFalse(result)
        self.mock_publish.assert_called_once()

    def test_12_regression_alex_ota_service_request_update_uses_ota_topic(self):
        from app import ota_service, store, _publish_ota_command
        # Verify wire-up
        self.assertEqual(ota_service.publisher, _publish_ota_command)

if __name__ == "__main__":
    unittest.main()
