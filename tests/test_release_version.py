import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import next_version


class TestReleaseVersion(unittest.TestCase):
    def test_parse_stable_version(self):
        self.assertEqual(
            next_version.parse_version("0.3.0"),
            (0, 3, 0),
        )

    def test_parse_rejects_prerelease_version(self):
        with self.assertRaises(ValueError):
            next_version.parse_version("0.3.0-rc.1")

    def test_fix_requires_patch_bump(self):
        self.assertEqual(
            next_version.classify_commit(
                "fix: repair MQTT connection",
                "",
            ),
            "patch",
        )

    def test_feat_requires_minor_bump(self):
        self.assertEqual(
            next_version.classify_commit(
                "feat: add local voice control",
                "",
            ),
            "minor",
        )

    def test_scoped_feat_requires_minor_bump(self):
        self.assertEqual(
            next_version.classify_commit(
                "feat(ui): add release history",
                "",
            ),
            "minor",
        )

    def test_breaking_bang_requires_major_bump(self):
        self.assertEqual(
            next_version.classify_commit(
                "feat!: replace command protocol",
                "",
            ),
            "major",
        )

    def test_breaking_change_body_requires_major_bump(self):
        self.assertEqual(
            next_version.classify_commit(
                "refactor: reorganize command service",
                "BREAKING CHANGE: old command payload is unsupported",
            ),
            "major",
        )

    def test_non_release_commit_is_ignored(self):
        self.assertIsNone(
            next_version.classify_commit(
                "docs: add release policy",
                "",
            )
        )

    def test_non_conventional_commit_is_ignored(self):
        self.assertIsNone(
            next_version.classify_commit(
                "update documentation",
                "",
            )
        )

    def test_highest_bump_uses_priority(self):
        commits = [
            {
                "subject": "fix: repair API",
                "body": "",
            },
            {
                "subject": "feat: add dashboard",
                "body": "",
            },
            {
                "subject": "docs: update guide",
                "body": "",
            },
        ]

        self.assertEqual(
            next_version.highest_bump(commits),
            "minor",
        )

    def test_bump_patch(self):
        self.assertEqual(
            next_version.bump_version("0.3.0", "patch"),
            "0.3.1",
        )

    def test_bump_minor(self):
        self.assertEqual(
            next_version.bump_version("0.3.1", "minor"),
            "0.4.0",
        )

    def test_bump_major(self):
        self.assertEqual(
            next_version.bump_version("0.4.2", "major"),
            "1.0.0",
        )

    def test_no_bump_keeps_current_version(self):
        self.assertEqual(
            next_version.bump_version("0.3.0", None),
            "0.3.0",
        )

    def test_prerelease_tag_is_not_stable(self):
        self.assertIsNone(
            next_version.STABLE_TAG_REGEX.fullmatch(
                "v0.3.0-rc.1"
            )
        )

    def test_stable_tag_is_accepted(self):
        self.assertIsNotNone(
            next_version.STABLE_TAG_REGEX.fullmatch(
                "v0.3.0"
            )
        )


if __name__ == "__main__":
    unittest.main()
