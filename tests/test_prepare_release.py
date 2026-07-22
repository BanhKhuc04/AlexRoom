import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import prepare_release


class TestPrepareRelease(unittest.TestCase):
    def test_no_release_required(self):
        result = {
            "releaseRequired": False,
        }

        self.assertEqual(
            prepare_release.render_release_notes(result),
            "No release required.",
        )

    def test_release_header_contains_versions(self):
        result = {
            "releaseRequired": True,
            "nextVersion": "0.4.0",
            "currentVersion": "0.3.0",
            "commitsInspected": 1,
            "commits": [
                {
                    "hash": "abc1234",
                    "subject": "feat: add dashboard",
                    "classification": "minor",
                }
            ],
        }

        notes = prepare_release.render_release_notes(result)

        self.assertIn("# ALEX v0.4.0", notes)
        self.assertIn("Previous version: 0.3.0", notes)
        self.assertIn("Commits included: 1", notes)

    def test_commits_are_grouped(self):
        result = {
            "releaseRequired": True,
            "nextVersion": "1.0.0",
            "currentVersion": "0.4.0",
            "commitsInspected": 4,
            "commits": [
                {
                    "hash": "4444444",
                    "subject": "docs: update guide",
                    "classification": None,
                },
                {
                    "hash": "3333333",
                    "subject": "fix: repair API",
                    "classification": "patch",
                },
                {
                    "hash": "2222222",
                    "subject": "feat: add dashboard",
                    "classification": "minor",
                },
                {
                    "hash": "1111111",
                    "subject": "feat!: replace protocol",
                    "classification": "major",
                },
            ],
        }

        notes = prepare_release.render_release_notes(result)

        self.assertIn("## Breaking Changes", notes)
        self.assertIn("## Features", notes)
        self.assertIn("## Fixes", notes)
        self.assertIn("## Maintenance", notes)

        self.assertIn("feat!: replace protocol", notes)
        self.assertIn("feat: add dashboard", notes)
        self.assertIn("fix: repair API", notes)
        self.assertIn("docs: update guide", notes)

    def test_empty_groups_are_not_rendered(self):
        result = {
            "releaseRequired": True,
            "nextVersion": "0.3.1",
            "currentVersion": "0.3.0",
            "commitsInspected": 1,
            "commits": [
                {
                    "hash": "abc1234",
                    "subject": "fix: repair API",
                    "classification": "patch",
                }
            ],
        }

        notes = prepare_release.render_release_notes(result)

        self.assertIn("## Fixes", notes)
        self.assertNotIn("## Features", notes)
        self.assertNotIn("## Breaking Changes", notes)
        self.assertNotIn("## Maintenance", notes)

    def test_commit_hash_is_rendered(self):
        result = {
            "releaseRequired": True,
            "nextVersion": "0.4.0",
            "currentVersion": "0.3.0",
            "commitsInspected": 1,
            "commits": [
                {
                    "hash": "abc1234",
                    "subject": "feat: add dashboard",
                    "classification": "minor",
                }
            ],
        }

        notes = prepare_release.render_release_notes(result)

        self.assertIn("(`abc1234`)", notes)


if __name__ == "__main__":
    unittest.main()
