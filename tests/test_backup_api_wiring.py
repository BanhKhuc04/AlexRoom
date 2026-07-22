from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP_SOURCE = (
    ROOT / "app.py"
).read_text(
    encoding="utf-8-sig"
)


class BackupApiWiringTests(
    unittest.TestCase
):
    def test_backup_service_is_imported(
        self,
    ) -> None:
        self.assertIn(
            "from alex_backup import BackupService",
            APP_SOURCE,
        )

    def test_backup_directory_defaults_next_to_database(
        self,
    ) -> None:
        self.assertIn(
            '"ALEX_BACKUP_DIR"',
            APP_SOURCE,
        )

        self.assertIn(
            'DATABASE_PATH.parent / "backups"',
            APP_SOURCE,
        )

    def test_backup_retention_is_configurable(
        self,
    ) -> None:
        self.assertIn(
            '"ALEX_BACKUP_RETENTION"',
            APP_SOURCE,
        )

        self.assertIn(
            'retention=ALEX_BACKUP_RETENTION',
            APP_SOURCE,
        )

    def test_post_backup_uses_backup_service(
        self,
    ) -> None:
        self.assertIn(
            '@app.post("/api/v1/backup")',
            APP_SOURCE,
        )

        self.assertIn(
            "result = backup_service.create()",
            APP_SOURCE,
        )

        self.assertIn(
            '"sha256": result["sha256"]',
            APP_SOURCE,
        )

    def test_backup_listing_endpoint_exists(
        self,
    ) -> None:
        self.assertIn(
            '@app.get("/api/v1/backups")',
            APP_SOURCE,
        )

        self.assertIn(
            '"items": backup_service.list_backups()',
            APP_SOURCE,
        )


if __name__ == "__main__":
    unittest.main()
