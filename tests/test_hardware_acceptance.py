import importlib.util
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import json

# Dynamically import the script
script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "hardware_acceptance.py")
spec = importlib.util.spec_from_file_location("hardware_acceptance", script_path)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

class TestHardwareAcceptance(unittest.TestCase):
    def setUp(self):
        self.mock_fetch_health = patch.object(acceptance, "fetch_health").start()
        self.mock_fetch_devices = patch.object(acceptance, "fetch_devices").start()
        self.mock_mqtt_client = patch.object(acceptance.mqtt, "Client").start()
        self.mock_sleep = patch("time.sleep").start()
        self.mock_exit = patch.object(sys, "exit").start()
        self.mock_exit.side_effect = Exception("sys.exit called")
        self.mock_save = patch.object(acceptance.Harness, "save_report").start()
        
        self.client_instance = MagicMock()
        self.mock_mqtt_client.return_value = self.client_instance

        # Default healthy environment
        self.mock_fetch_health.return_value = {"api": "online", "mqtt": "connected"}
        
        self.canonical_esp = {
            "node_id": "esp01",
            "connection": "online",
            "firmware": "1.0.0",
            "hardware_verified": False,
            "capabilities": {
                "test_led": {"verification_status": "basic_physical_validated", "command_allowed": True},
                "relay_1": {"verification_status": "restricted", "command_allowed": False},
                "relay_2": {"verification_status": "restricted", "command_allowed": False},
                "relay_3": {"verification_status": "restricted", "command_allowed": False},
                "relay_4": {"verification_status": "restricted", "command_allowed": False}
            }
        }
        self.mock_fetch_devices.return_value = {"items": [self.canonical_esp]}

    def tearDown(self):
        patch.stopall()

    def test_1_canonical_node_id_is_found_and_4_baseline_passes(self):
        harness = acceptance.Harness("baseline", False)
        harness.state["heartbeats"] = 1 # Simulate receiving heartbeat
        with self.assertRaises(Exception):
            harness.run_baseline()
        self.mock_exit.assert_called_with(0)
        self.mock_save.assert_called_with("baseline_check", self.canonical_esp, self.mock_fetch_health.return_value, "PHYSICAL_PASS")

    def test_2_old_id_compatibility_does_not_override_canonical_v1(self):
        # Even if there's a legacy record with `id`="esp01", the harness only selects the canonical one with `node_id`
        legacy_esp = {"id": "esp01", "connection": "offline"}
        self.mock_fetch_devices.return_value = {"items": [legacy_esp, self.canonical_esp]}
        harness = acceptance.Harness("baseline", False)
        harness.state["heartbeats"] = 1
        with self.assertRaises(Exception):
            harness.run_baseline()
        self.mock_exit.assert_called_with(0) # Will pass because it ignored legacy_esp and found canonical_esp

    def test_3_baseline_fails_when_esp01_missing(self):
        self.mock_fetch_devices.return_value = {"items": []}
        harness = acceptance.Harness("baseline", False)
        harness.state["heartbeats"] = 1
        with self.assertRaises(Exception):
            harness.run_baseline()
        self.mock_exit.assert_called_with(1)

    def test_5_relay_safety_truth_is_checked(self):
        # Break a safety truth
        unsafe_esp = dict(self.canonical_esp)
        unsafe_esp["capabilities"]["relay_1"]["command_allowed"] = True
        self.mock_fetch_devices.return_value = {"items": [unsafe_esp]}
        harness = acceptance.Harness("baseline", False)
        harness.state["heartbeats"] = 1
        with self.assertRaises(Exception):
            harness.run_baseline()
        self.mock_exit.assert_called_with(1)

    def test_6_only_one_normal_mqtt_client_lifecycle_occurs(self):
        harness = acceptance.Harness("baseline", False)
        harness.state["heartbeats"] = 1
        with self.assertRaises(Exception):
            harness.run_baseline()
        
        self.assertEqual(self.client_instance.connect.call_count, 1)
        self.assertEqual(self.client_instance.loop_start.call_count, 1)
        self.assertEqual(self.client_instance.loop_stop.call_count, 1)
        self.assertEqual(self.client_instance.disconnect.call_count, 1)

    def test_7_watch_recovery_requires_online_offline_online(self):
        harness = acceptance.Harness("watch-recovery", False)
        
        # Simulate state changes
        # 1. wait_initial_online -> gets online (canonical_esp has connection='online')
        # 2. wait_offline -> needs offline
        # 3. wait_recovery -> needs online
        
        def fetch_devices_side_effect():
            phase = harness._test_phase if hasattr(harness, '_test_phase') else 0
            if phase == 0:
                harness._test_phase = 1
                return {"items": [{"node_id": "esp01", "connection": "online"}]}
            elif phase == 1:
                harness._test_phase = 2
                return {"items": [{"node_id": "esp01", "connection": "offline"}]}
            else:
                return {"items": [{"node_id": "esp01", "connection": "online"}]}
                
        self.mock_fetch_devices.side_effect = fetch_devices_side_effect
        
        # Replace time.time() to simulate timeout if stuck, but here it shouldn't get stuck
        with patch("time.time", side_effect=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]):
            harness.run_watch_recovery()
            
        self.mock_save.assert_called_with("watch_recovery", None, self.mock_fetch_health.return_value, "PHYSICAL_PASS")

    def test_8_no_physical_transition_means_waiting_fail_never_physical_pass(self):
        harness = acceptance.Harness("watch-recovery", False)
        
        # Never goes offline
        self.mock_fetch_devices.return_value = {"items": [{"node_id": "esp01", "connection": "online"}]}
        
        # Timeout after 300s
        time_returns = [0] + [i for i in range(1, 400)]
        with patch("time.time", side_effect=time_returns):
            harness.run_watch_recovery()
            
        self.mock_save.assert_called_with("watch_recovery", None, self.mock_fetch_health.return_value, "WAITING_FOR_PHYSICAL_TEST")

if __name__ == "__main__":
    unittest.main()
