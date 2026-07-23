import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

import extract_release_notes


class TestExtractReleaseNotes(unittest.TestCase):
    def setUp(self):
        self.changelog = """# Changelog

# ALEX v0.5.0

Previous version: 0.4.0

## Features

- feat: add automatic GitHub releases

# ALEX v0.4.0

Previous version: 0.3.0

## Features

- feat: add release notes preview

## Fixes

- fix: clean release package
"""

    def test_extract_latest_release(self):
        notes = extract_release_notes.extract_release_notes(
            self.changelog,
            "0.5.0",
        )

        self.assertTrue(notes.startswith("# ALEX v0.5.0"))
        self.assertIn(
            "feat: add automatic GitHub releases",
            notes,
        )
        self.assertNotIn("# ALEX v0.4.0", notes)

    def test_extract_older_release(self):
        notes = extract_release_notes.extract_release_notes(
            self.changelog,
            "0.4.0",
        )

        self.assertTrue(notes.startswith("# ALEX v0.4.0"))
        self.assertIn(
            "feat: add release notes preview",
            notes,
        )
        self.assertIn(
            "fix: clean release package",
            notes,
        )
        self.assertNotIn("# ALEX v0.5.0", notes)

    def test_extract_expanded_release_heading(self):
        changelog = """# Changelog

# ALEX NEXUS OS v0.8.0 — Brain Text Intelligence

## Summary

- structured Brain proposals

# ALEX v0.7.0

- previous release
"""

        notes = extract_release_notes.extract_release_notes(
            changelog,
            "0.8.0",
        )

        self.assertTrue(
            notes.startswith(
                "# ALEX NEXUS OS v0.8.0 — Brain Text Intelligence"
            )
        )
        self.assertIn("structured Brain proposals", notes)
        self.assertNotIn("# ALEX v0.7.0", notes)
        self.assertNotIn("previous release", notes)

    def test_mixed_headings_preserve_section_boundaries(self):
        changelog = """# Changelog

# ALEX NEXUS OS v0.9.0 — Future

- future release

# ALEX NEXUS OS v0.8.0 — Brain Text Intelligence

- target release

# ALEX v0.7.0

- previous release
"""

        notes = extract_release_notes.extract_release_notes(
            changelog,
            "0.8.0",
        )

        self.assertIn("target release", notes)
        self.assertNotIn("future release", notes)
        self.assertNotIn("previous release", notes)

    def test_similar_versions_match_exactly(self):
        changelog = """# Changelog

# ALEX NEXUS OS v0.8.1 — Patch

- patch release

# ALEX NEXUS OS v0.8.0 — Brain Text Intelligence

- exact release

# ALEX v0.7.0

- previous release
"""

        notes = extract_release_notes.extract_release_notes(
            changelog,
            "0.8.0",
        )

        self.assertIn("exact release", notes)
        self.assertNotIn("patch release", notes)
        self.assertNotIn("previous release", notes)

    def test_missing_release_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Release notes not found",
        ):
            extract_release_notes.extract_release_notes(
                self.changelog,
                "9.9.9",
            )

    def test_invalid_version_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Invalid semantic version",
        ):
            extract_release_notes.extract_release_notes(
                self.changelog,
                "version-0.4",
            )

    def test_output_file_is_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "release-notes.md"

            extract_release_notes.write_output(
                output,
                "# ALEX v0.4.0\n",
            )

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "# ALEX v0.4.0\n",
            )

    def test_canonical_changelog_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            changelog = Path(temp_dir) / "CHANGELOG.md"
            changelog.write_text(
                "# Changelog\n",
                encoding="utf-8",
            )

            with patch.object(
                extract_release_notes,
                "CHANGELOG_FILE",
                changelog,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Refusing to overwrite",
                ):
                    extract_release_notes.write_output(
                        changelog,
                        "replacement",
                    )


if __name__ == "__main__":
    unittest.main()
