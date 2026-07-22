import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, call, MagicMock

# Dynamically import the deploy script
script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy", "alex-auto-update.py")
spec = importlib.util.spec_from_file_location("auto_update", script_path)
auto_update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto_update)

class TestAutoUpdate(unittest.TestCase):

    def setUp(self):
        self.mock_run_cmd = patch.object(auto_update, "run_cmd").start()
        self.mock_run_cmd_str = patch.object(auto_update, "run_cmd_str").start()
        self.mock_check_health = patch.object(auto_update, "check_health").start()
        self.mock_record_history = patch.object(auto_update, "record_history").start()
        self.mock_chown = patch.object(os, "geteuid", return_value=1000, create=True).start()
        
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "ota_state.json")
        self.lkg_file = os.path.join(self.temp_dir.name, "lkg.json")
        
        self.patch_state = patch.object(auto_update, "STATE_FILE", self.state_file).start()
        self.patch_lkg = patch.object(auto_update, "LKG_FILE", self.lkg_file).start()
        
        self.mock_disk_usage = patch.object(shutil, "disk_usage").start()
        mock_usage = MagicMock()
        mock_usage.free = 100000000
        self.mock_disk_usage.return_value = mock_usage
        
        self.mock_exit = patch.object(sys, "exit").start()
        self.mock_exit.side_effect = Exception("sys.exit called")

    def tearDown(self):
        patch.stopall()
        self.temp_dir.cleanup()

    def set_git_responses(self, fetch_rc=0, old="commit_a", new="commit_b", dirty=False, merge_base="commit_a", diff=[], merge="", reset="", version="1.0.0", old_version="0.9.0", app_py=True):
        def side_effect_str(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "rev-parse HEAD" in cmd_str: return old
            if "rev-parse origin/main" in cmd_str: return new
            if "status" in cmd_str: return "M file.txt" if dirty else ""
            if "merge-base" in cmd_str: return merge_base
            if "diff --name-only" in cmd_str: return "\n".join(diff)
            if "reset --hard" in cmd_str: return reset
            if "log" in cmd_str: return "commit msg"
            if "systemctl" in cmd_str: return ""
            return ""
            
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "fetch" in cmd_str: return "", fetch_rc
            if "show" in cmd_str and ":VERSION" in cmd_str:
                if old in cmd_str: return old_version, 0
                return version, 0 if version else 1
            if "ls-tree" in cmd_str and "app.py" in cmd_str:
                return "100644 blob abcdef app.py" if app_py else "", 0 if app_py else 1
            if "merge --ff-only" in cmd_str: return merge, 0
            return "", 0
            
        self.mock_run_cmd_str.side_effect = side_effect_str
        self.mock_run_cmd.side_effect = side_effect

    def test_1_no_update_available(self):
        self.set_git_responses(old="commit_a", new="commit_a")
        with self.assertRaises(Exception) as e:
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        self.mock_run_cmd.assert_any_call(["git", "fetch", "origin", "main"], check=False)

    def test_2_normal_fast_forward_update(self):
        self.set_git_responses(old="commit_a", new="commit_b", merge_base="commit_a")
        self.mock_check_health.return_value = True
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "ALEX AUTO UPDATE SUCCESS")
        
        # Verify state is updated properly
        state = auto_update.get_state()
        self.assertEqual(state.get("state"), "idle")
        
        lkg = auto_update.get_lkg()
        self.assertEqual(lkg.get("commit"), "commit_b")

    def test_3_dirty_tracked_tree_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", dirty=True)
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_4_divergent_history_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", merge_base="commit_c")
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_5_requirements_changed_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", diff=["requirements-orangepi.txt", "app.py"])
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_6_health_failure_causes_rollback(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.side_effect = [True, False, True] # pass pre-flight, fail post-activation, pass rollback
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd_str.call_args_list]
        self.assertIn(["git", "reset", "--hard", "commit_a"], calls)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "UPDATE_FAILED_ROLLED_BACK", "Health check failed")

    def test_7_rollback_restores_previous_commit(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.side_effect = [True, False, False] # pass pre, fail post, fail rollback
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd_str.call_args_list]
        self.assertIn(["git", "reset", "--hard", "commit_a"], calls)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "CRITICAL_ROLLBACK_FAILURE", "Health check failed")

    def test_8_failed_candidate_skipped_on_subsequent_runs(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        # Pre-seed a failed candidate in state
        auto_update.set_state({"state": "idle", "failed_candidates": {"commit_b": {"reason": "test"}}})
        
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        # Should not proceed to validate or activate
        self.mock_check_health.assert_not_called()

    def test_9_no_network_aborts_safely(self):
        self.set_git_responses(fetch_rc=1)
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_10_missing_version_file_rejected(self):
        self.set_git_responses(old="commit_a", new="commit_b", version=None)
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        state = auto_update.get_state()
        self.assertIn("commit_b", state["failed_candidates"])

    def test_11_older_version_rejected(self):
        self.set_git_responses(old="commit_a", new="commit_b", version="0.9.0", old_version="1.0.0")
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_12_missing_app_py_rejected(self):
        self.set_git_responses(old="commit_a", new="commit_b", app_py=False)
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_13_insufficient_disk_space_rejected(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        mock_usage = MagicMock()
        mock_usage.free = 10000 # ~10KB free
        self.mock_disk_usage.return_value = mock_usage
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_14_unhealthy_core_before_update_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.return_value = False
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        state = auto_update.get_state()
        # Should not record as candidate failure, just aborts
        self.assertNotIn("commit_b", state.get("failed_candidates", {}))

    def test_15_interrupted_recovery_success(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        auto_update.set_state({"state": "verifying", "old_commit": "commit_a", "candidate": "commit_b"})
        self.mock_check_health.return_value = True
        
        with self.assertRaises(Exception):
            auto_update.run_update()
        
        self.mock_exit.assert_called_with(0)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "ALEX AUTO UPDATE SUCCESS")
        state = auto_update.get_state()
        self.assertEqual(state["state"], "idle")

    def test_16_interrupted_recovery_rollback(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        auto_update.set_state({"state": "activating", "old_commit": "commit_a", "candidate": "commit_b"})
        self.mock_check_health.return_value = True # Rollback check passes
        
        with self.assertRaises(Exception):
            auto_update.run_update()
            
        self.mock_exit.assert_called_with(1)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "UPDATE_FAILED_ROLLED_BACK", "Interrupted during activation")

    def test_17_rollback_failure(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.side_effect = [True, False]
        # Simulate rollback failure by throwing an exception during reset
        def reset_side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                if "HEAD" in cmd: return "commit_a"
                if "origin/main" in cmd: return "commit_b"
            if "merge-base" in cmd: return "commit_a"
            if "status" in cmd: return ""
            if "reset" in cmd and "commit_a" in cmd:
                raise Exception("Git reset failed")
            return "ok"
        self.mock_run_cmd_str.side_effect = reset_side_effect
        
        with self.assertRaises(Exception):
            auto_update.run_update()
            
        self.mock_exit.assert_called_with(1)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "CRITICAL_ROLLBACK_FAILURE", "Git reset failed")
        
    def test_18_interrupted_verification(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        auto_update.set_state({"state": "verifying", "old_commit": "commit_a", "candidate": "commit_b"})
        self.mock_check_health.side_effect = [False, True]
        
        with self.assertRaises(Exception):
            auto_update.run_update()
            
        self.mock_exit.assert_called_with(1)
        # Should rollback
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "UPDATE_FAILED_ROLLED_BACK", "Health check failed after recovery")

    def test_19_interrupted_rollback(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        auto_update.set_state({"state": "rolling_back", "old_commit": "commit_a", "candidate": "commit_b"})
        self.mock_check_health.return_value = True
        with self.assertRaises(Exception):
            auto_update.run_update()
            
        self.mock_exit.assert_called_with(1)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "UPDATE_FAILED_ROLLED_BACK", "Interrupted during rollback")

    import sys
    @unittest.skipIf(sys.platform == "win32", "fcntl not available on Windows")
    @patch("fcntl.flock")
    def test_20_concurrent_updater_lock(self, mock_flock):
        # Simulate a lock file existing that cannot be acquired
        mock_flock.side_effect = BlockingIOError("Concurrent lock")
        with self.assertRaises(Exception):
            auto_update.main()
        self.mock_exit.assert_called_with(0)

if __name__ == "__main__":
    unittest.main()

