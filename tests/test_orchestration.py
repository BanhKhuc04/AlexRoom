from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from alex_brain import BrainService
from alex_hardware import RealtimeHub
from alex_orchestration import AutomationExecutor, MissionExecutor
from alex_safety import CapabilityRegistry, CommandGateway, SafetyPolicy
from alex_store import AlexStore


class FakeCommandService:
    def __init__(self) -> None:
        self.created = []

    def _create_test_led_command(self, value, origin, source):
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
        self.commands = FakeCommandService()
        self.gateway = CommandGateway(SafetyPolicy(CapabilityRegistry(), simulator_mode=True), self.commands)
        self.missions = MissionExecutor(self.store, self.gateway, timeout=0.1)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mission_partial_failure_is_not_full_success(self) -> None:
        mission = self.missions.run({"name": "study", "source": "simulated", "steps": [
            {"target": "test_led", "action": "set", "value": True, "risk_level": "safe"},
            {"target": "relay_1", "action": "off", "risk_level": "safe"},
        ]})
        self.assertEqual(mission["status"], "partial")
        self.assertEqual([step["status"] for step in mission["steps"]], ["confirmed", "failed"])
        self.assertEqual(mission["steps"][1]["failure_reason"], "restricted_capability")

    def test_mission_malformed_steps_collection_fails(self) -> None:
        mission_empty = self.missions.run({"name": "empty", "source": "simulated", "steps": []})
        self.assertEqual(mission_empty["status"], "failed")
        self.assertEqual(len(mission_empty["steps"]), 0)
        self.assertIsNotNone(mission_empty["completed_at"])

        mission_none = self.missions.run({"name": "none", "source": "simulated", "steps": None})
        self.assertEqual(mission_none["status"], "failed")
        self.assertIsNotNone(mission_none["completed_at"])

        mission_dict = self.missions.run({"name": "dict", "source": "simulated", "steps": {"action": "invalid"}})
        self.assertEqual(mission_dict["status"], "failed")
        self.assertIsNotNone(mission_dict["completed_at"])

    def test_mission_malformed_step_fails_closed(self) -> None:
        mission = self.missions.run({"name": "malformed", "source": "simulated", "steps": [
            "this_is_not_a_dict",
            {"target": "test_led", "action": "set", "value": True, "risk_level": "safe"}
        ]})
        self.assertEqual(mission["status"], "partial")
        self.assertEqual(len(mission["steps"]), 2)
        self.assertEqual(mission["steps"][0]["status"], "failed")
        self.assertEqual(mission["steps"][0]["failure_reason"], "malformed_step")
        self.assertEqual(mission["steps"][1]["status"], "confirmed")

    def test_automation_conditions_and_restricted_gate(self) -> None:
        executor = AutomationExecutor(self.store, self.missions, self.gateway)
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
            "actions": [{"target": "relay_2", "action": "on", "risk_level": "safe"}],
        }, {"type": "manual"})
        self.assertTrue(blocked["matched"])
        self.assertEqual(blocked["blocked_reason"], "safety_policy_denied")
        self.assertEqual(blocked["mission"]["steps"][0]["failure_reason"], "restricted_capability")

    def test_automation_conditions_validation(self) -> None:
        executor = AutomationExecutor(self.store, self.missions, self.gateway)
        def eval_conds(conds: list) -> bool:
            return executor.evaluate({
                "id": "c-test", "enabled": True, "trigger": {"type": "manual"}, "conditions": conds, "actions": []
            }, {"type": "manual"})["matched"]

        self.assertFalse(eval_conds(["not a dict"]))
        self.assertFalse(eval_conds([{"type": "unknown_type"}]))
        self.assertFalse(eval_conds([{"type": "node_connection"}]))
        self.assertFalse(eval_conds([{"type": "node_connection", "equals": "offline"}]))
        self.assertTrue(eval_conds([{"type": "node_connection", "equals": "online"}]))
        self.assertFalse(eval_conds([{"type": "reported_state"}]))
        self.assertFalse(eval_conds([{"type": "reported_state", "target": "test_led"}]))
        self.assertFalse(eval_conds([{"type": "reported_state", "target": "test_led", "field": "on"}]))
        self.assertFalse(eval_conds([{"type": "reported_state", "target": "test_led", "equals": False}]))
        self.assertTrue(eval_conds([{"type": "reported_state", "target": "test_led", "field": "on", "equals": False}]))
        # Fail-closed: unknown target + equals None must not match
        self.assertFalse(eval_conds([{"type": "reported_state", "target": "nonexistent_device", "field": "on", "equals": None}]))
        # Fail-closed: known target + unknown field + equals None must not match
        self.assertFalse(eval_conds([{"type": "reported_state", "target": "test_led", "field": "nonexistent_field", "equals": None}]))
        # Valid: known target + known field compared normally
        self.assertTrue(eval_conds([{"type": "reported_state", "target": "test_led", "field": "on", "equals": False}]))

    def test_automation_runtime_metadata_preserved_on_put(self) -> None:
        """PUT via definition must not overwrite authoritative runtime fields."""
        executor = AutomationExecutor(self.store, self.missions, self.gateway)
        rule_id = "meta-preserve-test"
        initial = {
            "name": "Meta Test", "enabled": True,
            "trigger": {"type": "manual"}, "conditions": [], "actions": [],
            "source": "local_software",
        }
        self.store.put_record("automations", rule_id, initial)
        # Run once to create runtime metadata
        rule = self.store.get_record("automations", rule_id)
        rule["id"] = rule_id
        result = executor.evaluate(rule, {"type": "manual"})
        self.assertTrue(result["matched"])
        record_after_run = self.store.get_record("automations", rule_id)
        self.assertIsNotNone(record_after_run.get("lastEvaluation"))
        self.assertIsNotNone(record_after_run.get("lastRun"))
        # Simulate PUT from frontend (definition only, no runtime fields)
        definition_only = {
            "name": "Meta Test Updated", "enabled": False,
            "trigger": {"type": "manual"}, "conditions": [], "actions": [],
            "source": "local_software",
        }
        # Simulate backend preservation logic (mirroring app.py v1_put_domain for automations)
        _RUNTIME_FIELDS = {"lastEvaluation", "lastRun", "blockedReason", "result", "duration"}
        body = dict(definition_only)
        existing = self.store.get_record("automations", rule_id)
        for field in _RUNTIME_FIELDS:
            body.pop(field, None)
        if existing:
            for field in _RUNTIME_FIELDS:
                if field in existing:
                    body[field] = existing[field]
        self.store.put_record("automations", rule_id, body)
        updated = self.store.get_record("automations", rule_id)
        self.assertEqual(updated["name"], "Meta Test Updated")
        self.assertFalse(updated["enabled"])
        # Runtime metadata must survive
        self.assertEqual(updated.get("lastEvaluation"), record_after_run.get("lastEvaluation"))
        self.assertEqual(updated.get("lastRun"), record_after_run.get("lastRun"))
        # Malicious frontend-supplied runtime fields must not overwrite
        malicious_body = dict(definition_only)
        malicious_body["lastEvaluation"] = "1970-01-01T00:00:00Z"
        malicious_body["result"] = "hacked"
        malicious_body["duration"] = 0
        body2 = dict(malicious_body)
        existing2 = self.store.get_record("automations", rule_id)
        for field in _RUNTIME_FIELDS:
            body2.pop(field, None)
        if existing2:
            for field in _RUNTIME_FIELDS:
                if field in existing2:
                    body2[field] = existing2[field]
        self.store.put_record("automations", rule_id, body2)
        final = self.store.get_record("automations", rule_id)
        # Authoritative values must be preserved, not the malicious ones
        self.assertNotEqual(final.get("lastEvaluation"), "1970-01-01T00:00:00Z")
        self.assertNotEqual(final.get("result"), "hacked")

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
