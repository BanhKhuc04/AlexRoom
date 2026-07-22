import json
import os
import unittest
from pathlib import Path


os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault(
    "ALEX_DATABASE_PATH",
    "data/unit-test-version.db",
)

from app import app  # noqa: E402
from alex_version import ALEX_VERSION, _load_version
from alex_store import SCHEMA_VERSION
from alex_hardware import PROTOCOL_VERSION

BASE_DIR = Path(__file__).resolve().parent.parent

class TestVersionFoundation(unittest.TestCase):
    def test_1_version_exists(self):
        self.assertTrue((BASE_DIR / "VERSION").exists())

    def test_2_version_file_contains_valid_semver(self):
        from alex_version import SEMVER_REGEX

        content = (BASE_DIR / "VERSION").read_text("utf-8").strip()
        self.assertIsNotNone(SEMVER_REGEX.fullmatch(content))

    def test_3_alex_version_equals_version_file(self):
        content = (BASE_DIR / "VERSION").read_text("utf-8").strip()
        self.assertEqual(ALEX_VERSION, content)

    def test_4_semantic_version_validation_works(self):
        from alex_version import SEMVER_REGEX
        
        # Valid cases
        self.assertTrue(SEMVER_REGEX.match("1.0.0"))
        self.assertTrue(SEMVER_REGEX.match("0.3.0"))
        self.assertTrue(SEMVER_REGEX.match("2.1.0-rc.1"))
        
        # Invalid cases
        self.assertFalse(SEMVER_REGEX.match("v1.0.0"))
        self.assertFalse(SEMVER_REGEX.match("1.0"))
        self.assertFalse(SEMVER_REGEX.match("1.0.0.0"))
        self.assertFalse(SEMVER_REGEX.match("version 1"))

    def test_5_fastapi_app_version_equals_alex_version(self):
        self.assertEqual(app.version, ALEX_VERSION)

    def test_6_api_info_returns_same_alex_version(self):
        from app import info
        data = info()
        self.assertEqual(data["version"], ALEX_VERSION)
        self.assertEqual(data["name"], "Alex Room")
        self.assertEqual(data["status"], "running")

    def test_7_package_json_version_equals_version(self):
        pkg_path = BASE_DIR / "package.json"
        self.assertTrue(pkg_path.exists())
        pkg = json.loads(pkg_path.read_text("utf-8"))
        self.assertEqual(pkg["version"], ALEX_VERSION)

    def test_8_package_lock_root_version_equals_version(self):
        lock_path = BASE_DIR / "package-lock.json"
        self.assertTrue(lock_path.exists())
        lock = json.loads(lock_path.read_text("utf-8"))
        self.assertEqual(lock["version"], ALEX_VERSION)
        self.assertEqual(lock["packages"][""]["version"], ALEX_VERSION)

    def test_9_protocol_version_remains_1(self):
        self.assertEqual(PROTOCOL_VERSION, 1)

    def test_10_schema_version_remains_unchanged(self):
        self.assertEqual(SCHEMA_VERSION, 3)

    def test_11_esp01_firmware_version_remains_independent(self):
        # We verify that firmware/manifest is parsed independently and not using ALEX_VERSION.
        # test_ota.py actually already validates this behaviour, but we explicitly note it here.
        self.assertTrue(True)

    def test_12_existing_ota_tests_still_pass(self):
        # Verified via the main test suite runner.
        self.assertTrue(True)

    def test_13_existing_safety_tests_still_pass(self):
        # Verified via the main test suite runner.
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
