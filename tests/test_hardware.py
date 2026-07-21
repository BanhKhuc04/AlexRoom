from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from alex_hardware import CommandService, RealtimeHub
from alex_simulator import Esp01Simulator
from alex_store import AlexStore


def wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class HardwareVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "alex.db")
        self.store.migrate()
        self.published: list[dict] = []

        def publish(topic: str, payload: str, qos: int, retain: bool) -> bool:
            self.published.append({"topic": topic, "payload": json.loads(payload), "qos": qos, "retain": retain})
            return True

        self.service = CommandService(
            self.store, publish, RealtimeHub(), ack_timeout=0.04,
            reported_timeout=0.04, max_retries=2, heartbeat_timeout=0.06,
        )
        self.service.start()
        self.service.handle_heartbeat({
            "protocolVersion": 1, "nodeId": "esp01", "online": True,
            "firmware": "test", "rssi": -50,
        }, "simulated")

    def tearDown(self) -> None:
        self.service.stop()
        self.temp.cleanup()

    def test_normal_ack_and_reported_state_confirm_only_after_match(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        command_id = command["command_id"]
        self.assertTrue(command_id.startswith("cmd_"))
        self.assertEqual(self.service.command(command_id)["phase"], "waiting_ack")
        self.assertEqual(self.published[0]["qos"], 1)
        self.assertEqual(self.published[0]["payload"]["commandId"], command_id)

        self.assertTrue(self.service.handle_ack({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command_id, "status": "accepted",
        }, "simulated"))
        self.assertEqual(self.service.command(command_id)["phase"], "waiting_reported_state")
        self.service.handle_reported({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command_id,
            "target": "test_led", "state": {"on": True},
        }, "simulated")
        confirmed = self.service.command(command_id)
        self.assertEqual(confirmed["phase"], "confirmed")
        self.assertIsNotNone(confirmed["confirmed_at"])
        self.assertGreaterEqual(len(self.store.command_events(command_id)), 6)

    def test_wrong_command_id_is_ignored_and_mismatch_fails(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        self.assertFalse(self.service.handle_ack({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": "cmd_wrong", "status": "accepted",
        }))
        self.service.handle_ack({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"], "status": "accepted",
        })
        self.service.handle_reported({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"],
            "target": "test_led", "state": {"on": False},
        })
        failed = self.service.command(command["command_id"])
        self.assertEqual(failed["phase"], "failed")
        self.assertEqual(failed["failure_reason"], "reported_state_mismatch")

    def test_no_ack_retries_twice_then_times_out(self) -> None:
        command = self.service.create_test_led_command(False, "test", "simulated")
        self.assertTrue(wait_for(lambda: self.service.command(command["command_id"])["phase"] == "timed_out", 1.5))
        final = self.service.command(command["command_id"])
        self.assertEqual(final["retry_count"], 2)
        self.assertEqual(len(self.published), 3)
        self.assertEqual(final["failure_reason"], "ack_timeout")

    def test_ack_without_reported_state_times_out_without_retrying_action(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        self.service.handle_ack({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"], "status": "accepted",
        })
        self.assertTrue(wait_for(lambda: self.service.command(command["command_id"])["phase"] == "timed_out", 0.8))
        final = self.service.command(command["command_id"])
        self.assertEqual(final["failure_reason"], "reported_state_timeout")
        self.assertEqual(len(self.published), 1)

    def test_offline_node_rejects_command_before_publish(self) -> None:
        self.service.mark_offline("simulated")
        with self.assertRaisesRegex(RuntimeError, "esp01_offline"):
            self.service.create_test_led_command(True, "test", "simulated")
        self.assertEqual(self.published, [])

    def test_cancelled_command_cannot_become_late_false_success(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        cancelled = self.service.cancel(command["command_id"])
        self.assertEqual(cancelled["phase"], "cancelled")
        self.service.handle_ack({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"], "status": "accepted",
        })
        self.service.handle_reported({
            "protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"],
            "target": "test_led", "state": {"on": True},
        })
        self.assertEqual(self.service.command(command["command_id"])["phase"], "cancelled")

    def test_backend_restart_marks_pending_command_failed_and_preserves_audit(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        self.service.stop()
        restarted = CommandService(self.store, lambda *_: True, RealtimeHub())
        restarted.start()
        try:
            recovered = restarted.command(command["command_id"])
            self.assertEqual(recovered["phase"], "failed")
            self.assertEqual(recovered["failure_reason"], "backend_restarted")
        finally:
            restarted.stop()

    def test_duplicate_ack_is_idempotent_and_heartbeat_expires(self) -> None:
        command = self.service.create_test_led_command(True, "test", "simulated")
        ack = {"protocolVersion": 1, "nodeId": "esp01", "commandId": command["command_id"], "status": "accepted"}
        self.assertTrue(self.service.handle_ack(ack))
        self.assertTrue(self.service.handle_ack(ack))
        self.assertEqual(self.service.command(command["command_id"])["phase"], "waiting_reported_state")
        self.assertTrue(wait_for(lambda: self.service.device()["connection"] == "offline", 0.3))

    def test_simulator_duplicate_delivery_executes_once(self) -> None:
        self.service.ack_timeout = 0.3
        self.service.reported_timeout = 0.3
        simulator = Esp01Simulator(
            self.service.handle_heartbeat, self.service.handle_ack, self.service.handle_reported,
            scenario="duplicate_message",
        )
        self.service.publisher = simulator.publish
        simulator.start()
        try:
            command = self.service.create_test_led_command(True, "test", "simulated")
            self.assertTrue(wait_for(lambda: self.service.command(command["command_id"])["phase"] == "confirmed"))
            self.assertEqual(simulator.execution_count, 1)
        finally:
            simulator.stop()


if __name__ == "__main__":
    unittest.main()
