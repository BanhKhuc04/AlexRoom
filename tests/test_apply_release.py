import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import apply_release


class TestApplyRelease(unittest.TestCase):
    def make_result(self):
        return {
            "releaseRequired": True,
            "currentVersion": "0.3.0",
            "nextVersion": "0.4.0",
            "bump": "minor",
            "commitsInspected": 1,
            "commits": [
                {
                    "hash": "abc1234",
                    "subject": "feat: add release system",
                    "classification": "minor",
                }
            ],
        }

    def test_build_release_files_updates_all_versions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            version_file = root / "VERSION"
            package_file = root / "package.json"
            lock_file = root / "package-lock.json"
            changelog_file = root / "CHANGELOG.md"

            package_file.write_text(
                json.dumps(
                    {
                        "name": "alexroom-mark-iii",
                        "version": "0.3.0",
                    }
                ),
                encoding="utf-8",
            )

            lock_file.write_text(
                json.dumps(
                    {
                        "name": "alexroom-mark-iii",
                        "version": "0.3.0",
                        "packages": {
                            "": {
                                "name": "alexroom-mark-iii",
                                "version": "0.3.0",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                apply_release,
                "VERSION_FILE",
                version_file,
            ), patch.object(
                apply_release,
                "PACKAGE_FILE",
                package_file,
            ), patch.object(
                apply_release,
                "PACKAGE_LOCK_FILE",
                lock_file,
            ), patch.object(
                apply_release,
                "CHANGELOG_FILE",
                changelog_file,
            ):
                files = apply_release.build_release_files(
                    self.make_result()
                )

            package = json.loads(files[package_file])
            package_lock = json.loads(files[lock_file])

            self.assertEqual(files[version_file], "0.4.0\n")
            self.assertEqual(package["version"], "0.4.0")
            self.assertEqual(package_lock["version"], "0.4.0")
            self.assertEqual(
                package_lock["packages"][""]["version"],
                "0.4.0",
            )
            self.assertIn("# Changelog", files[changelog_file])
            self.assertIn("# ALEX v0.4.0", files[changelog_file])

    def test_existing_changelog_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            version_file = root / "VERSION"
            package_file = root / "package.json"
            lock_file = root / "package-lock.json"
            changelog_file = root / "CHANGELOG.md"

            package_file.write_text(
                '{"version":"0.3.0"}',
                encoding="utf-8",
            )

            lock_file.write_text(
                '{"version":"0.3.0","packages":{"":{"version":"0.3.0"}}}',
                encoding="utf-8",
            )

            changelog_file.write_text(
                "# ALEX v0.3.0\n\nPrevious release.\n",
                encoding="utf-8",
            )

            with patch.object(
                apply_release,
                "VERSION_FILE",
                version_file,
            ), patch.object(
                apply_release,
                "PACKAGE_FILE",
                package_file,
            ), patch.object(
                apply_release,
                "PACKAGE_LOCK_FILE",
                lock_file,
            ), patch.object(
                apply_release,
                "CHANGELOG_FILE",
                changelog_file,
            ):
                files = apply_release.build_release_files(
                    self.make_result()
                )

            changelog = files[changelog_file]

            self.assertTrue(
                changelog.index("# ALEX v0.4.0")
                < changelog.index("# ALEX v0.3.0")
            )
            self.assertIn("Previous release.", changelog)

    def test_changelog_header_remains_at_top(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            version_file = root / "VERSION"
            package_file = root / "package.json"
            lock_file = root / "package-lock.json"
            changelog_file = root / "CHANGELOG.md"

            package_file.write_text(
                '{"version":"0.3.0"}',
                encoding="utf-8",
            )

            lock_file.write_text(
                '{"version":"0.3.0","packages":{"":{"version":"0.3.0"}}}',
                encoding="utf-8",
            )

            changelog_file.write_text(
                "# Changelog\n\n"
                "# ALEX v0.3.0\n\n"
                "Previous release.\n",
                encoding="utf-8",
            )

            with patch.object(
                apply_release,
                "VERSION_FILE",
                version_file,
            ), patch.object(
                apply_release,
                "PACKAGE_FILE",
                package_file,
            ), patch.object(
                apply_release,
                "PACKAGE_LOCK_FILE",
                lock_file,
            ), patch.object(
                apply_release,
                "CHANGELOG_FILE",
                changelog_file,
            ):
                files = apply_release.build_release_files(
                    self.make_result()
                )

            changelog = files[changelog_file]

            self.assertTrue(
                changelog.startswith(
                    "# Changelog\n\n# ALEX v0.4.0"
                )
            )
            self.assertEqual(
                changelog.count("# Changelog"),
                1,
            )
            self.assertLess(
                changelog.index("# ALEX v0.4.0"),
                changelog.index("# ALEX v0.3.0"),
            )

    def test_dirty_working_tree_is_rejected(self):
        with patch.object(
            apply_release,
            "run_git",
            return_value=" M app.py",
        ):
            with self.assertRaises(RuntimeError):
                apply_release.ensure_clean_working_tree()

    def test_existing_target_tag_is_rejected(self):
        with patch.object(
            apply_release,
            "run_git",
            return_value="v0.4.0",
        ):
            with self.assertRaises(RuntimeError):
                apply_release.ensure_target_tag_missing("0.4.0")


if __name__ == "__main__":
    unittest.main()
