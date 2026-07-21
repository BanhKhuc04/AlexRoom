import importlib.util
import json
import os
import sys
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
        self.mock_check_health = patch.object(auto_update, "check_health").start()
        self.mock_record_history = patch.object(auto_update, "record_history").start()
        self.mock_chown = patch.object(os, "geteuid", return_value=1000, create=True).start()
        self.mock_exit = patch.object(sys, "exit").start()
        self.mock_exit.side_effect = Exception("sys.exit called")

    def tearDown(self):
        patch.stopall()

    def set_git_responses(self, fetch="", old="commit_a", new="commit_b", dirty=False, merge_base="commit_a", diff=[], merge="", reset=""):
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "fetch" in cmd_str: return fetch
            if "rev-parse HEAD" in cmd_str: return old
            if "rev-parse origin/main" in cmd_str: return new
            if "status" in cmd_str: return "M file.txt" if dirty else ""
            if "merge-base" in cmd_str: return merge_base
            if "diff --name-only" in cmd_str: return "\n".join(diff)
            if "merge --ff-only" in cmd_str: return merge
            if "reset --hard" in cmd_str: return reset
            if "log" in cmd_str: return "commit msg"
            if "systemctl" in cmd_str: return ""
            return ""
        self.mock_run_cmd.side_effect = side_effect

    def test_1_no_update_available(self):
        self.set_git_responses(old="commit_a", new="commit_a")
        with self.assertRaises(Exception) as e:
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        self.mock_run_cmd.assert_any_call(["git", "fetch", "origin", "main"])
        # ensure merge is never called
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertFalse(any("merge" in " ".join(cmd) for cmd in calls))

    def test_2_normal_fast_forward_update(self):
        self.set_git_responses(old="commit_a", new="commit_b", merge_base="commit_a")
        self.mock_check_health.return_value = True
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "ALEX AUTO UPDATE SUCCESS")
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertIn(["git", "merge", "--ff-only", "origin/main"], calls)
        self.assertIn(["systemctl", "restart", "alex-core.service"], calls)

    def test_3_dirty_tracked_tree_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", dirty=True)
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertNotIn(["git", "merge", "--ff-only", "origin/main"], calls)

    def test_4_untracked_report_files_do_not_block_update(self):
        # We test this implicitly by ensuring the git status command uses -uno
        self.set_git_responses(old="commit_a", new="commit_b", dirty=False)
        self.mock_check_health.return_value = True
        with self.assertRaises(Exception):
            auto_update.run_update()
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertIn(["git", "status", "--porcelain", "-uno"], calls)
        self.assertIn(["git", "merge", "--ff-only", "origin/main"], calls)

    def test_5_divergent_history_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", merge_base="commit_c")
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)

    def test_6_requirements_changed_aborts(self):
        self.set_git_responses(old="commit_a", new="commit_b", diff=["requirements-orangepi.txt", "app.py"])
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertNotIn(["git", "merge", "--ff-only", "origin/main"], calls)

    def test_7_health_success_deployment_accepted(self):
        # Covered mostly by test 2, verifying health = True causes exit(0)
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.return_value = True
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(0)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "ALEX AUTO UPDATE SUCCESS")

    def test_8_health_failure_causes_rollback(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.side_effect = [False, True] # fail first check, pass rollback check
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertIn(["git", "reset", "--hard", "commit_a"], calls)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "UPDATE_FAILED_ROLLED_BACK", "Health check failed")
        self.assertEqual(calls.count(["systemctl", "restart", "alex-core.service"]), 2)

    def test_9_rollback_restores_previous_commit(self):
        self.set_git_responses(old="commit_a", new="commit_b")
        self.mock_check_health.side_effect = [False, False] # fail first, fail rollback
        with self.assertRaises(Exception):
            auto_update.run_update()
        self.mock_exit.assert_called_with(1)
        calls = [c[0][0] for c in self.mock_run_cmd.call_args_list]
        self.assertIn(["git", "reset", "--hard", "commit_a"], calls)
        self.mock_record_history.assert_called_with("commit_a", "commit_b", "CRITICAL_ROLLBACK_FAILURE", "Health check failed")

    def test_10_secrets_never_appear_in_update_history(self):
        # Record history just takes the commits and messages. We test that the log entry
        # doesn't dump env vars by asserting how record_history creates the payload.
        patch.stopall()
        # Mock run_cmd to return a fake commit message without secrets
        with patch.object(auto_update, "run_cmd", return_value="fix: safe fix") as mock_cmd, \
             patch("builtins.open", new_callable=unittest.mock.mock_open) as mock_file:
            auto_update.record_history("commit_a", "commit_b", "SUCCESS")
            # Get what was written
            written = mock_file().write.call_args[0][0]
            data = json.loads(written)
            self.assertEqual(data["changes"], ["fix: safe fix"])
            self.assertEqual(data["result"], "SUCCESS")
            # Ensure no env secrets are implicitly dumped
            self.assertNotIn("MQTT_PASSWORD", written)
            self.assertNotIn("ALEX_API_KEY", written)


if __name__ == "__main__":
    unittest.main()
