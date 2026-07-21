import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock

import app as alex_app
from app import (
    app, ota_service, realtime_hub, store, command_service, capability_registry
)
from alex_hardware import HEARTBEAT_TOPIC

class TestOtaHeartbeatRegression(unittest.TestCase):
    @patch("app.mqtt_client")
    def test_startup_and_heartbeat_integration(self, mock_mqtt):
        async def run_lifespan():
            try:
                async with alex_app.lifespan(app):
                    # We must clear the store of any OTA records for a clean test
                    with store._lock, store.session() as db:
                        db.execute("DELETE FROM domain_records WHERE domain=? AND record_id=?", ("ota", "esp01"))
                        
                    # Set up an OTA operation
                    store.put_record("ota", "esp01", {
                        "operationId": "test_op",
                        "targetVersion": "1.0.1",
                        "status": "installing" # simulating mid-OTA
                    })

                    # 3 & 4: Normal ESP01 heartbeat updates canonical state & OTA receives it
                    # 6: Heartbeat with old/wrong firmware does NOT confirm
                    heartbeat_old = {
                        "protocolVersion": 1,
                        "nodeId": "esp01",
                        "online": True,
                        "firmware": "1.0.0",
                    }
                    
                    # We simulate receiving an MQTT heartbeat
                    mock_msg_old = MagicMock()
                    mock_msg_old.topic = HEARTBEAT_TOPIC
                    mock_msg_old.payload = json.dumps(heartbeat_old).encode("utf-8")
                    
                    # Trigger on_message (which calls command_service.handle_heartbeat, which emits to realtime_hub, which calls OTA listener)
                    from app import on_message
                    on_message(mock_mqtt, None, mock_msg_old)
                    
                    # Check OTA state is STILL installing
                    state = store.get_record("ota", "esp01")
                    self.assertEqual(state.get("status"), "installing")
                    
                    # Check canonical device state is updated
                    device = command_service.device()
                    self.assertEqual(device["firmware"], "1.0.0")

                    # 5: Heartbeat with target firmware confirms matching OTA operation
                    heartbeat_new = {
                        "protocolVersion": 1,
                        "nodeId": "esp01",
                        "online": True,
                        "firmware": "1.0.1",
                    }
                    mock_msg_new = MagicMock()
                    mock_msg_new.topic = HEARTBEAT_TOPIC
                    mock_msg_new.payload = json.dumps(heartbeat_new).encode("utf-8")
                    
                    on_message(mock_mqtt, None, mock_msg_new)
                    
                    # Check OTA state is now CONFIRMED
                    state = store.get_record("ota", "esp01")
                    self.assertEqual(state.get("status"), "confirmed")
                    
                    # Check canonical device state is updated to 1.0.1
                    device = command_service.device()
                    self.assertEqual(device["firmware"], "1.0.1")

                    # 7: relay_1..relay_4 remain restricted
                    node_truth = capability_registry.get_node_status("esp01")
                    self.assertIsNotNone(node_truth)
                    for i in range(1, 5):
                        relay_cap = node_truth["capabilities"].get(f"relay_{i}")
                        self.assertIsNotNone(relay_cap)
                        self.assertEqual(relay_cap["verification_status"], "restricted")
            except Exception as e:
                self.fail(f"Lifespan startup or event processing crashed: {e}")

        asyncio.run(run_lifespan())

if __name__ == "__main__":
    unittest.main()
