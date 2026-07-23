from __future__ import annotations

import os
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

os.environ["MQTT_PASSWORD"] = "unit-test-password"
os.environ["ALEX_API_KEY"] = "unit-test-api-key"
os.environ["ALEX_SIMULATOR"] = "0"

# Set up test database before importing app
_temp_dir = tempfile.TemporaryDirectory()
os.environ["ALEX_DATABASE_PATH"] = str(Path(_temp_dir.name) / "alex.db")

import app as alex_app
from app import DomainRecordRequest

class ApiScenesTests(unittest.TestCase):
    def setUp(self):
        # Ensure clean state and tables exist
        alex_app.store.migrate()

    def tearDown(self):
        # Clean up records between tests if needed, or rely on migration/tempdir
        pass

    @classmethod
    def tearDownClass(cls):
        _temp_dir.cleanup()

    def test_case_a_existing_production_style_scene_preserves_metadata(self):
        """Case A — existing production-style Scene preserves authoritative metadata"""
        # 1. Seed the DB with a production-style scene
        alex_app.store.put_record("scenes", "home", {
            "name": "Home",
            "safety_level": "safe",
            "steps": [],
            "execution": "backend_mode_contract"
        })

        # 2. Simulate client PUT attempting to overwrite authoritative fields
        payload = DomainRecordRequest(body={
            "name": "Home Edited",
            "safety_level": "hacked",
            "execution": "custom_script",
            "risk_level": "none",
            "steps": [{"node_id": "esp01", "target": "test_led", "action": "set", "value": True}]
        })

        res = alex_app.v1_put_domain("scenes", "home", payload, None)
        self.assertTrue(res["saved"])

        # 3. Verify metadata was preserved from existing DB and not overwritten
        updated = alex_app.store.get_record("scenes", "home")
        self.assertEqual(updated["name"], "Home Edited")
        self.assertEqual(updated["safety_level"], "safe")
        self.assertEqual(updated["execution"], "backend_mode_contract")
        self.assertNotIn("risk_level", updated)  # Since it didn't exist in original DB

    def test_case_b_incoming_authoritative_fields_cannot_be_invented_for_new_scene(self):
        """Case B — incoming authoritative fields cannot be invented for a new Scene"""
        # 1. Ensure scene does not exist (by using a unique name)

        # 2. Client submits new scene with authoritative fields
        payload = DomainRecordRequest(body={
            "name": "New Scene",
            "safety_level": "safe",
            "execution": "backend_mode_contract",
            "risk_level": "low",
            "steps": []
        })

        alex_app.v1_put_domain("scenes", "new_scene", payload, None)

        # 3. Verify backend stripped the client-provided fields
        created = alex_app.store.get_record("scenes", "new_scene")
        self.assertEqual(created["name"], "New Scene")
        self.assertNotIn("safety_level", created)
        self.assertNotIn("execution", created)
        self.assertNotIn("risk_level", created)

    def test_case_c_existing_scene_risk_level_is_preserved(self):
        """Case C — if an existing Scene has risk_level, verify it is preserved"""
        alex_app.store.put_record("scenes", "existing_risk", {
            "name": "Existing Risk",
            "risk_level": "high",
            "steps": []
        })

        payload = DomainRecordRequest(body={
            "name": "Existing Risk Edited",
            "risk_level": "low",  # client tries to lower risk
            "safety_level": "safe" # client tries to invent safety level
        })

        alex_app.v1_put_domain("scenes", "existing_risk", payload, None)

        updated = alex_app.store.get_record("scenes", "existing_risk")
        self.assertEqual(updated["name"], "Existing Risk Edited")
        self.assertEqual(updated["risk_level"], "high") # preserved
        self.assertNotIn("safety_level", updated) # stripped because original didn't have it

if __name__ == "__main__":
    unittest.main()
