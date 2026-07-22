import re
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_FILE = (
    BASE_DIR
    / ".github"
    / "workflows"
    / "release.yml"
)


class TestReleaseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_FILE.read_text(
            encoding="utf-8",
        )

    def test_workflow_file_has_no_utf8_bom(self):
        raw = WORKFLOW_FILE.read_bytes()

        self.assertFalse(
            raw.startswith(b"\xef\xbb\xbf"),
        )

    def test_release_is_manual_only(self):
        trigger_section = self.workflow.split(
            "\npermissions:",
            maxsplit=1,
        )[0]

        self.assertIn(
            "workflow_dispatch:",
            trigger_section,
        )

        automatic_triggers = (
            "\n  push:",
            "\n  pull_request:",
            "\n  pull_request_target:",
            "\n  schedule:",
            "\n  workflow_run:",
        )

        for trigger in automatic_triggers:
            self.assertNotIn(
                trigger,
                trigger_section,
            )

    def test_workflow_has_required_permissions(self):
        self.assertRegex(
            self.workflow,
            re.compile(
                r"(?m)^permissions:\s*\n"
                r"  contents: write\s*$"
            ),
        )

        self.assertIn(
            "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
            self.workflow,
        )

    def test_safe_mode_is_default(self):
        self.assertIn(
            "default: validate",
            self.workflow,
        )

        self.assertIn(
            "- validate",
            self.workflow,
        )

        self.assertIn(
            "- publish",
            self.workflow,
        )

        self.assertIn(
            'RELEASE_CONFIRM" != "RELEASE"',
            self.workflow,
        )

    def test_publish_steps_are_guarded(self):
        guard = "if: inputs.mode == 'publish'"

        self.assertGreaterEqual(
            self.workflow.count(guard),
            3,
        )

        self.assertIn(
            "Check publish state",
            self.workflow,
        )

        self.assertIn(
            "Create annotated tag",
            self.workflow,
        )

        self.assertIn(
            "Publish GitHub Release",
            self.workflow,
        )

    def test_current_runtime_actions_are_declared(self):
        required_actions = (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/setup-node@v7",
            'python-version: "3.13"',
            'node-version: "24"',
        )

        for action in required_actions:
            self.assertIn(
                action,
                self.workflow,
            )

    def test_release_versions_must_be_synchronized(self):
        required_versions = (
            '"VERSION": canonical',
            '"package.json": package.get("version")',
            '"package-lock.json": package_lock.get("version")',
            '"package-lock root"',
            'expected_subject = f"chore(release): v{version}"',
        )

        for item in required_versions:
            self.assertIn(
                item,
                self.workflow,
            )

    def test_full_quality_and_packaging_are_required(self):
        required_commands = (
            "python -m pip install -r requirements.txt",
            "npm ci",
            "npm run check:all",
            "./scripts/release.ps1",
            "scripts/extract_release_notes.py",
            "zipfile.ZipFile",
            "hashlib.sha256",
        )

        for command in required_commands:
            self.assertIn(
                command,
                self.workflow,
            )

    def test_archive_checks_required_and_forbidden_content(self):
        required_files = (
            "VERSION",
            "CHANGELOG.md",
            "app.py",
            "alex_version.py",
            "package.json",
            "package-lock.json",
            "requirements.txt",
            "scripts/apply_release.py",
            "scripts/prepare_release.py",
            "scripts/next_version.py",
            "scripts/extract_release_notes.py",
        )

        for filename in required_files:
            self.assertIn(
                filename,
                self.workflow,
            )

        forbidden_content = (
            '".pio"',
            '".pio-venv"',
            '"__pycache__"',
            'lowered == ".env"',
            'lowered == "secrets.yaml"',
            'lowered.endswith(".pyc")',
            'lowered.endswith(".db")',
            'lowered.endswith(".db-wal")',
            'lowered.endswith(".db-shm")',
        )

        for pattern in forbidden_content:
            self.assertIn(
                pattern,
                self.workflow,
            )

    def test_release_publication_has_collision_guards(self):
        required_guards = (
            '"$TAG^{commit}"',
            "Existing tag points to another commit",
            "Published release already exists",
            "gh release create",
            "--draft",
            "gh release upload",
            "--clobber",
            "gh release edit",
            "--draft=false",
            "--latest",
        )

        for guard in required_guards:
            self.assertIn(
                guard,
                self.workflow,
            )

        self.assertNotIn(
            "apply_release.py --apply",
            self.workflow,
        )

        self.assertNotRegex(
            self.workflow,
            re.compile(
                r"(?m)^\s+git commit(?:\s|$)"
            ),
        )


if __name__ == "__main__":
    unittest.main()
