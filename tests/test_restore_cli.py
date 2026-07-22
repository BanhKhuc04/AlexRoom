from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alex_backup import BackupService
from alex_store import AlexStore

import sys

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

sys.path.insert(
    0,
    str(SCRIPTS),
)

import restore_backup


class RestoreCliTests(
    unittest.TestCase
):
    def test_paths_follow_database_parent(
        self,
    ) -> None:
        database, backup, rollback = (
            restore_backup.resolve_paths(
                {
                    "ALEX_DATABASE_PATH":
                        "/var/lib/alex/alex.db"
                }
            )
        )

        self.assertEqual(
            database,
            Path(
                "/var/lib/alex/alex.db"
            ),
        )

        self.assertEqual(
            backup,
            Path(
                "/var/lib/alex/backups"
            ),
        )

        self.assertEqual(
            rollback,
            Path(
                "/var/lib/alex/"
                "restore-rollback"
            ),
        )

    def test_active_service_blocks_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(
                RuntimeError,
                "is active",
            ):
                restore_backup.restore_backup(
                    "alex-demo.db",
                    confirmation="RESTORE",
                    database=root / "alex.db",
                    backup_dir=root / "backups",
                    rollback_dir=root / "rollback",
                    service_checker=lambda _: True,
                )

    def test_confirmation_is_required(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(
                PermissionError,
                "RESTORE",
            ):
                restore_backup.restore_backup(
                    "alex-demo.db",
                    confirmation="NO",
                    database=root / "alex.db",
                    backup_dir=root / "backups",
                    rollback_dir=root / "rollback",
                    service_checker=lambda _: False,
                )

    def test_validate_and_restore_when_service_is_stopped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            database = root / "alex.db"

            store = AlexStore(database)
            store.migrate()

            store.put_record(
                "settings",
                "demo",
                {
                    "value": "before",
                },
            )

            backup_service = BackupService(
                store,
                root / "backups",
                retention=5,
            )

            backup = backup_service.create()

            store.put_record(
                "settings",
                "demo",
                {
                    "value": "after",
                },
            )

            validated = (
                restore_backup.validate_backup(
                    backup["file"],
                    database=database,
                    backup_dir=root / "backups",
                    rollback_dir=root / "rollback",
                )
            )

            self.assertTrue(
                validated["validated"]
            )

            result = (
                restore_backup.restore_backup(
                    backup["file"],
                    confirmation="RESTORE",
                    database=database,
                    backup_dir=root / "backups",
                    rollback_dir=root / "rollback",
                    service_checker=lambda _: False,
                )
            )

            self.assertTrue(
                result["restored"]
            )

            restored_store = AlexStore(
                database
            )

            record = (
                restored_store.get_record(
                    "settings",
                    "demo",
                )
            )

            self.assertEqual(
                record["value"],
                "before",
            )


if __name__ == "__main__":
    unittest.main()
