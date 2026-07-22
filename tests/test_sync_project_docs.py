import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

import sync_project_docs


class TestSyncProjectDocs(unittest.TestCase):
    def test_status_block_contains_current_version(self):
        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        self.assertIn(
            "ALEX Core version: `0.6.0`",
            block,
        )

        self.assertIn(
            "Current production release: `v0.6.0`",
            block,
        )

    def test_status_block_contains_verified_production(self):
        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        required = (
            "Orange Pi",
            "alex-core.service",
            "alex-update.timer",
            "FastAPI",
            "SQLite",
            "SSE + MQTT",
            "Mosquitto",
            "ESP01 hardware node: online",
            "hardware verified",
            "Simulator in production: disabled",
        )

        for value in required:
            self.assertIn(value, block)

    def test_release_pipeline_is_documented(self):
        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        required = (
            "ALEX Prepare Release",
            "ALEX Release",
            "Semantic Version",
            "SHA256",
            "Annotated Git tag",
            "mode=publish",
            "RELEASE",
        )

        for value in required:
            self.assertIn(value, block)

    def test_safety_restrictions_remain_documented(self):
        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        self.assertIn(
            "Relay outputs remain restricted",
            block,
        )

        self.assertIn(
            "must not publish directly to MQTT",
            block,
        )

        self.assertIn(
            "ALEX Core remains the authority boundary",
            block,
        )

    def test_inject_after_first_h1(self):
        source = (
            "# Existing Document\n\n"
            "Historical content.\n"
        )

        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        result = sync_project_docs.inject_status_block(
            source,
            block,
        )

        self.assertTrue(
            result.startswith(
                "# Existing Document\n\n"
                + sync_project_docs.START_MARKER
            )
        )

        self.assertIn(
            "Historical content.",
            result,
        )

    def test_existing_managed_block_is_replaced(self):
        old_block = sync_project_docs.build_status_block(
            "0.5.0"
        )

        source = (
            "# Existing Document\n\n"
            + old_block
            + "\n\n"
            + "Historical content.\n"
        )

        new_block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        result = sync_project_docs.inject_status_block(
            source,
            new_block,
        )

        self.assertIn(
            "ALEX Core version: `0.6.0`",
            result,
        )

        self.assertNotIn(
            "ALEX Core version: `0.5.0`",
            result,
        )

        self.assertEqual(
            result.count(
                sync_project_docs.START_MARKER
            ),
            1,
        )

        self.assertEqual(
            result.count(
                sync_project_docs.END_MARKER
            ),
            1,
        )

        self.assertIn(
            "Historical content.",
            result,
        )

    def test_unmatched_marker_is_rejected(self):
        source = (
            "# Broken\n\n"
            + sync_project_docs.START_MARKER
            + "\n"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "unmatched status markers",
        ):
            sync_project_docs.inject_status_block(
                source,
                "replacement",
            )

    def test_duplicate_managed_blocks_are_rejected(self):
        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        source = (
            "# Broken\n\n"
            + block
            + "\n\n"
            + block
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "duplicate managed status blocks",
        ):
            sync_project_docs.inject_status_block(
                source,
                block,
            )

    def test_historical_versions_are_preserved(self):
        source = (
            "# History\n\n"
            "Release v0.4.0 was important.\n"
            "Release v0.5.0 followed.\n"
        )

        block = sync_project_docs.build_status_block(
            "0.6.0"
        )

        result = sync_project_docs.inject_status_block(
            source,
            block,
        )

        self.assertIn(
            "Release v0.4.0 was important.",
            result,
        )

        self.assertIn(
            "Release v0.5.0 followed.",
            result,
        )

    def test_canonical_status_document(self):
        document = (
            sync_project_docs
            .build_canonical_status_document(
                "0.6.0"
            )
        )

        self.assertTrue(
            document.startswith(
                "# ALEX Current Project Status"
            )
        )

        self.assertIn(
            "Canonical Core version: `0.6.0`",
            document,
        )

        self.assertEqual(
            document.count(
                sync_project_docs.START_MARKER
            ),
            1,
        )

        self.assertEqual(
            document.count(
                sync_project_docs.END_MARKER
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
