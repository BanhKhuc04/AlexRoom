from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from alex_backup import BackupService
from alex_store import AlexStore


class BackupServiceTests(
    unittest.TestCase
):
    def test_create_backup_with_metadata_and_checksum(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            store.put_record(
                "scenes",
                "study",
                {
                    "name": "Study",
                },
            )

            service = BackupService(
                store,
                root / "backups",
                retention=7,
            )

            result = service.create()

            database_path = (
                service.backup_dir
                / result["file"]
            )

            metadata_path = (
                service.backup_dir
                / result["metadata_file"]
            )

            self.assertTrue(
                database_path.is_file()
            )

            self.assertTrue(
                metadata_path.is_file()
            )

            self.assertEqual(
                result["integrity"],
                "ok",
            )

            self.assertGreater(
                result["size_bytes"],
                0,
            )

            digest = hashlib.sha256(
                database_path.read_bytes()
            ).hexdigest()

            self.assertEqual(
                result["sha256"],
                digest,
            )

            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                metadata["sha256"],
                digest,
            )

            db = sqlite3.connect(
                database_path
            )

            try:
                integrity = db.execute(
                    "PRAGMA quick_check"
                ).fetchone()

                record = db.execute(
                    """
                    SELECT body_json
                    FROM domain_records
                    WHERE domain=?
                    AND record_id=?
                    """,
                    (
                        "scenes",
                        "study",
                    ),
                ).fetchone()

            finally:
                db.close()

            self.assertEqual(
                integrity[0],
                "ok",
            )

            self.assertIsNotNone(
                record
            )

            body = json.loads(
                record[0]
            )

            self.assertEqual(
                body["name"],
                "Study",
            )

    def test_list_backups_returns_newest_first(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            service = BackupService(
                store,
                root / "backups",
                retention=5,
            )

            first = service.create()
            second = service.create()

            items = (
                service.list_backups()
            )

            self.assertEqual(
                len(items),
                2,
            )

            self.assertEqual(
                items[0]["file"],
                second["file"],
            )

            self.assertEqual(
                items[1]["file"],
                first["file"],
            )

    def test_retention_removes_old_database_and_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            service = BackupService(
                store,
                root / "backups",
                retention=2,
            )

            created = [
                service.create(),
                service.create(),
                service.create(),
            ]

            database_files = list(
                service.backup_dir.glob(
                    "alex-*.db"
                )
            )

            metadata_files = list(
                service.backup_dir.glob(
                    "alex-*.json"
                )
            )

            self.assertEqual(
                len(database_files),
                2,
            )

            self.assertEqual(
                len(metadata_files),
                2,
            )

            oldest = created[0]

            self.assertFalse(
                (
                    service.backup_dir
                    / oldest["file"]
                ).exists()
            )

            self.assertFalse(
                (
                    service.backup_dir
                    / oldest[
                        "metadata_file"
                    ]
                ).exists()
            )

    def test_missing_metadata_is_reported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            service = BackupService(
                store,
                root / "backups",
            )

            result = service.create()

            metadata_path = (
                service.backup_dir
                / result["metadata_file"]
            )

            metadata_path.unlink()

            items = (
                service.list_backups()
            )

            self.assertEqual(
                len(items),
                1,
            )

            self.assertEqual(
                items[0]["integrity"],
                "metadata_missing",
            )

            self.assertEqual(
                len(items[0]["sha256"]),
                64,
            )

    def test_invalid_retention_is_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AlexStore(
                Path(directory)
                / "alex.db"
            )

            with self.assertRaisesRegex(
                ValueError,
                "at least 1",
            ):
                BackupService(
                    store,
                    Path(directory)
                    / "backups",
                    retention=0,
                )


if __name__ == "__main__":
    unittest.main()
