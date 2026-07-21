from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from alex_brain import BrainService
from alex_hardware import RealtimeHub
from alex_orchestration import AutomationExecutor, MissionExecutor
from alex_store import AlexStore


class FakeCommands:
    def __init__(self) -> None:
        self.created = []

    def create_test_led_command(self, value, origin, source):
        command = {"command_id": f"cmd_{len(self.created)}", "phase": "confirmed", "failure_reason": None}
        self.created.append((value, origin, source, command))
        return command

    def command(self, command_id):
        return next(item[3] for item in self.created if item[3]["command_id"] == command_id)

    def device(self):
        return {"connection": "online", "reported_state": {"test_led": {"on": False}}}


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AlexStore(Path(self.temp.name) / "alex.db")
        self.store.migrate()
        self.commands = FakeCommands()
        self.missions = MissionExecutor(self.store, self.commands, timeout=0.1)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mission_partial_failure_is_not_full_success(self) -> None:
        mission = self.missions.run({"name": "study", "source": "simulated", "steps": [
            {"target": "test_led", "action": "set", "value": True, "risk_level": "safe"},
            {"target": "door_lock", "action": "unlock", "risk_level": "restricted"},
        ]})
        self.assertEqual(mission["status"], "partial")
        self.assertEqual([step["status"] for step in mission["steps"]], ["confirmed", "failed"])

    def test_automation_conditions_and_restricted_gate(self) -> None:
        executor = AutomationExecutor(self.store, self.missions, self.commands)
        safe = executor.evaluate({
            "id": "manual-safe", "name": "manual", "enabled": True,
            "trigger": {"type": "manual"}, "conditions": [{"type": "node_connection", "equals": "online"}],
            "actions": [{"target": "test_led", "action": "set", "value": True, "risk_level": "safe"}],
            "source": "simulated",
        }, {"type": "manual"})
        self.assertTrue(safe["matched"])
        self.assertEqual(safe["mission"]["status"], "completed")
        blocked = executor.evaluate({
            "id": "restricted", "enabled": True, "trigger": {"type": "manual"}, "conditions": [],
            "actions": [{"target": "uv", "action": "on", "risk_level": "restricted"}],
        }, {"type": "manual"})
        self.assertEqual(blocked["blocked_reason"], "restricted_action")

    def test_wol_magic_packet_and_bounded_confirmation(self) -> None:
        sent = []
        probes = iter([False, True])
        brain = BrainService(
            self.store, RealtimeHub(), "AA:BB:CC:DD:EE:FF", "192.0.2.1",
            timeout=0.2, sender=sent.append, probe=lambda: next(probes, True),
        )
        state = brain.wake()
        self.assertEqual(state["state"], "waking")
        self.assertEqual(len(sent[0]), 102)
        deadline = time.monotonic() + 0.3
        while brain.status()["state"] == "waking" and time.monotonic() < deadline:
            time.sleep(0.01)
        brain.wait()
        self.assertEqual(brain.status()["state"], "online")
        self.assertFalse(brain.status()["hardware_verified"])


if __name__ == "__main__":
    unittest.main()
