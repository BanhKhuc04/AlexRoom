import re
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

PREPARE_WORKFLOW = (
    BASE_DIR
    / ".github"
    / "workflows"
    / "prepare-release.yml"
)

RELEASE_WORKFLOW = (
    BASE_DIR
    / ".github"
    / "workflows"
    / "release.yml"
)


class TestPrepareReleaseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepare = PREPARE_WORKFLOW.read_text(
            encoding="utf-8",
        )

        cls.release = RELEASE_WORKFLOW.read_text(
            encoding="utf-8",
        )

    def test_prepare_workflow_has_no_bom(self):
        self.assertFalse(
            PREPARE_WORKFLOW.read_bytes().startswith(
                b"\xef\xbb\xbf"
            )
        )

    def test_prepare_is_manual_only(self):
        trigger = self.prepare.split(
            "\npermissions:",
            maxsplit=1,
        )[0]

        self.assertIn(
            "workflow_dispatch:",
            trigger,
        )

        forbidden = (
            "\n  push:",
            "\n  pull_request:",
            "\n  schedule:",
            "\n  workflow_run:",
        )

        for item in forbidden:
            self.assertNotIn(
                item,
                trigger,
            )

    def test_prepare_requires_write_permission(self):
        self.assertRegex(
            self.prepare,
            re.compile(
                r"(?m)^permissions:\s*\n"
                r"  contents: write\s*$"
            ),
        )

    def test_prepare_requires_confirmation(self):
        self.assertIn(
            'PREPARE_CONFIRM" != "PREPARE"',
            self.prepare,
        )

        self.assertIn(
            "confirm=PREPARE",
            self.prepare,
        )

    def test_current_version_must_have_stable_tag(self):
        self.assertIn(
            'CURRENT_TAG="v$CURRENT_VERSION"',
            self.prepare,
        )

        self.assertIn(
            "does not have a stable tag",
            self.prepare,
        )

        self.assertIn(
            "git merge-base",
            self.prepare,
        )

        self.assertIn(
            "--is-ancestor",
            self.prepare,
        )

    def test_prepare_and_publish_share_lock(self):
        expected = (
            "group: alex-release-control"
        )

        self.assertIn(
            expected,
            self.prepare,
        )

        self.assertIn(
            expected,
            self.release,
        )

    def test_current_runtime_actions_are_used(self):
        required = (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/setup-node@v7",
            'python-version: "3.13"',
            'node-version: "24"',
        )

        for item in required:
            self.assertIn(
                item,
                self.prepare,
            )

    def test_semantic_release_is_calculated(self):
        self.assertIn(
            "from next_version import calculate_release",
            self.prepare,
        )

        self.assertIn(
            'result["releaseRequired"]',
            self.prepare,
        )

        self.assertIn(
            'result["nextVersion"]',
            self.prepare,
        )

        self.assertIn(
            'result["bump"]',
            self.prepare,
        )

    def test_release_files_are_applied(self):
        self.assertIn(
            "python scripts/apply_release.py --apply",
            self.prepare,
        )

        required_files = (
            "CHANGELOG.md",
            "VERSION",
            "package-lock.json",
            "package.json",
        )

        for filename in required_files:
            self.assertIn(
                filename,
                self.prepare,
            )

    def test_prepared_versions_are_validated(self):
        required = (
            '"VERSION": canonical',
            '"package.json"',
            '"package-lock.json"',
            '"package-lock root"',
            "# Changelog",
            "# ALEX v",
        )

        for item in required:
            self.assertIn(
                item,
                self.prepare,
            )

    def test_full_quality_gate_is_required(self):
        self.assertIn(
            "npm run check:all",
            self.prepare,
        )

        self.assertIn(
            "git diff --check",
            self.prepare,
        )

    def test_release_commit_is_exact(self):
        self.assertIn(
            'chore(release): v$NEXT_VERSION',
            self.prepare,
        )

        self.assertIn(
            "github-actions[bot]",
            self.prepare,
        )

        self.assertIn(
            "41898282+github-actions[bot]",
            self.prepare,
        )

    def test_remote_main_is_revalidated_before_push(self):
        self.assertIn(
            "Revalidate main before push",
            self.prepare,
        )

        self.assertIn(
            "git rev-parse HEAD^",
            self.prepare,
        )

        self.assertIn(
            "git rev-parse origin/main",
            self.prepare,
        )

        self.assertIn(
            "origin/main changed",
            self.prepare,
        )

    def test_push_is_fast_forward_only(self):
        self.assertIn(
            "git push origin HEAD:main",
            self.prepare,
        )

        self.assertNotIn(
            "--force",
            self.prepare,
        )

        self.assertNotIn(
            "--force-with-lease",
            self.prepare,
        )

    def test_prepare_never_creates_tag_or_release(self):
        forbidden = (
            "git tag -a",
            "git push origin v",
            "gh release create",
            "gh release upload",
            "gh release edit",
        )

        for item in forbidden:
            self.assertNotIn(
                item,
                self.prepare,
            )

    def test_summary_explicitly_stops_before_publish(self):
        self.assertIn(
            "No tag or GitHub Release was created",
            self.prepare,
        )

        self.assertIn(
            "Verify production first",
            self.prepare,
        )

        self.assertIn(
            "mode: \\`publish\\`",
            self.prepare,
        )


if __name__ == "__main__":
    unittest.main()
