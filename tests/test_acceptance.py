import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Dynamically import the script
script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "alex_acceptance.py")
spec = importlib.util.spec_from_file_location("alex_acceptance", script_path)
alex_acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alex_acceptance)

class TestAcceptance(unittest.TestCase):
    def setUp(self):
        self.mock_run_cmd = patch.object(alex_acceptance, "run_cmd").start()
        self.mock_exit = patch.object(sys, "exit").start()
        self.mock_exit.side_effect = Exception("sys.exit called")
        self.mock_path_exists = patch.object(Path, "exists").start()
        self.mock_path_is_file = patch.object(Path, "is_file").start()
        self.mock_path_read_text = patch.object(Path, "read_text").start()
        self.mock_path_stat = patch.object(Path, "stat").start()
        self.mock_path_write = patch.object(Path, "write_text").start()
        self.mock_path_glob = patch.object(Path, "glob").start()
        self.mock_urlopen = patch("urllib.request.urlopen").start()
        self.mock_sqlite_integrity = patch.object(alex_acceptance, "sqlite_integrity").start()
        self.mock_sqlite_quick_check = patch.object(alex_acceptance, "sqlite_quick_check").start()
        self.mock_time = patch("time.time").start()
        self.mock_time.return_value = 1000000.0

    def tearDown(self):
        patch.stopall()

    def set_system_state(
        self,
        failed_units=False,
        core_active=True,
        missing_health_timer=False,
        db_ok=True,
        health_stale=False,
        mqtt_ok=True,
        esp01_ok=True,
        corrupt_backup=False,
        missing_backup=False,
        rollback_invalid=False,
        env_secure=True,
        stale_heartbeat=False,
    ):
        def cmd_side_effect(cmd, **kwargs):
            mock_res = MagicMock()
            cmd_str = " ".join(cmd)
            if "systemctl --failed" in cmd_str:
                mock_res.stdout = "random.service failed\n" if failed_units else "0 loaded units listed\n"
                mock_res.returncode = 0
            elif "is-active alex-core.service" in cmd_str:
                mock_res.stdout = "active\n" if core_active else "inactive\n"
                mock_res.returncode = 0
            elif "is-active alex-health.timer" in cmd_str:
                mock_res.stdout = "inactive\n" if missing_health_timer else "active\n"
                mock_res.returncode = 0
            elif "is-active" in cmd_str:
                mock_res.stdout = "active\n"
                mock_res.returncode = 0
            else:
                mock_res.stdout = ""
                mock_res.returncode = 0
            return mock_res
        
        self.mock_run_cmd.side_effect = cmd_side_effect

        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_path_read_text.return_value = "0.3.0"
        
        mock_stat = MagicMock()
        mock_stat.st_size = 1000
        mock_stat.st_mode = 0o100600 if env_secure else 0o100644
        mock_stat.st_uid = 0
        mock_stat.st_mtime = 1000000.0 - 3600 # 1 hour old
        self.mock_path_stat.return_value = mock_stat

        self.mock_path_glob.return_value = [] if missing_backup else [Path("backup1.db")]
        self.mock_sqlite_integrity.return_value = db_ok
        self.mock_sqlite_quick_check.return_value = not corrupt_backup

        health_data = {
            "available": True,
            "stale": health_stale,
            "status": "healthy" if mqtt_ok and esp01_ok and not health_stale else "degraded",
            "report": {
                "checks": {
                    "hardware_runtime": {
                        "mqtt": "connected" if mqtt_ok else "disconnected",
                        "device": "online" if esp01_ok else "offline",
                        "heartbeat_age_seconds": 70 if stale_heartbeat else 10
                    },
                    "database": {"status": "healthy"},
                    "core_service": {"status": "healthy"},
                    "backup": {"status": "healthy"},
                    "update_timer": {"status": "healthy"},
                }
            }
        }
        mock_res = MagicMock()
        mock_res.status = 200
        mock_res.read.return_value = json.dumps(health_data).encode("utf-8")
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_res
        self.mock_urlopen.return_value = mock_context

        # For rollback/LKG reading
        def read_text_side_effect(*args, **kwargs):
            return "invalid json" if rollback_invalid else '{"commit": "1234567"}'

        self.mock_path_read_text.side_effect = read_text_side_effect
        
        # We also need to mock open for reading json files
        original_open = open
        def open_mock(file, *args, **kwargs):
            if "last_known_good.json" in str(file) or "ota_state.json" in str(file):
                m = MagicMock()
                m.__enter__.return_value = m
                m.read.return_value = "invalid" if rollback_invalid else '{"commit": "123"}'
                return m
            return original_open(file, *args, **kwargs)
        
        self.open_patcher = patch('builtins.open', side_effect=open_mock).start()

    def test_fully_healthy(self):
        self.set_system_state()
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(0)

    def test_esp01_offline(self):
        self.set_system_state(esp01_ok=False)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_mqtt_disconnected(self):
        self.set_system_state(mqtt_ok=False)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_database_quick_check_failure(self):
        self.set_system_state(db_ok=False)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_corrupt_backup(self):
        self.set_system_state(corrupt_backup=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_stale_health(self):
        self.set_system_state(health_stale=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_stale_heartbeat_seconds(self):
        self.set_system_state(stale_heartbeat=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_legacy_heartbeat_age_ignored(self):
        # Even if legacy heartbeat_age is stale, if heartbeat_age_seconds is missing or healthy, it should ignore the legacy field
        # We simulate stale_heartbeat=False (so heartbeat_age_seconds=10) but inject a stale heartbeat_age
        self.set_system_state(stale_heartbeat=False)
        
        # Retrieve the data it would have returned
        mock_resp = self.mock_urlopen.return_value.__enter__.return_value
        health_data = json.loads(mock_resp.read.return_value.decode("utf-8"))
        
        # Inject the stale legacy field
        health_data["report"]["checks"]["hardware_runtime"]["heartbeat_age"] = 100
        mock_resp.read.return_value = json.dumps(health_data).encode("utf-8")
        
        with self.assertRaises(Exception):
            alex_acceptance.main()
        
        # It should exit with 0 because heartbeat_age is ignored
        self.mock_exit.assert_called_with(0)

    def test_missing_health_timer(self):
        self.set_system_state(missing_health_timer=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_insecure_env_permissions(self):
        self.set_system_state(env_secure=False)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_rollback_state_invalid(self):
        self.set_system_state(rollback_invalid=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

    def test_failed_systemd_unit(self):
        self.set_system_state(failed_units=True)
        with self.assertRaises(Exception):
            alex_acceptance.main()
        self.mock_exit.assert_called_with(1)

if __name__ == "__main__":
    unittest.main()
