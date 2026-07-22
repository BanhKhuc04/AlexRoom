from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alex_scheduled_backup import (
    backup_filename,
    prune_backups,
    run_scheduled_backup,
)
from alex_store import AlexStore


class ScheduledBackupTests(unittest.TestCase):

    def test_backup_filename_is_utc_and_timestamped(self) -> None:
        now = datetime(
            2026,
            7,
            22,
            12,
            34,
            56,
            123456,
            tzinfo=timezone.utc,
        )

        self.assertEqual(
            backup_filename(now),
            "alex-20260722T123456123456Z.db",
        )

    def test_scheduled_backup_creates_readable_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "alex.db"
            backups = root / "backups"

            store = AlexStore(database)
            store.migrate()

            created = run_scheduled_backup(
                database_path=database,
                backup_dir=backups,
                keep_count=3,
                now=datetime(
                    2026,
                    7,
                    22,
                    1,
                    2,
                    3,
                    tzinfo=timezone.utc,
                ),
            )

            self.assertTrue(created.is_file())
            self.assertGreater(created.stat().st_size, 0)

            connection = sqlite3.connect(created)
            try:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
            finally:
                connection.close()

            self.assertIsNotNone(result)
            self.assertEqual(result[0], "ok")

    def test_retention_keeps_only_newest_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = Path(directory)

            names = [
                "alex-20260719T000000000000Z.db",
                "alex-20260720T000000000000Z.db",
                "alex-20260721T000000000000Z.db",
                "alex-20260722T000000000000Z.db",
            ]

            for name in names:
                (backup_dir / name).write_bytes(b"test")

            unrelated = backup_dir / "do-not-delete.txt"
            unrelated.write_text(
                "keep",
                encoding="utf-8",
            )

            removed = prune_backups(
                backup_dir,
                keep_count=2,
            )

            remaining = sorted(
                path.name
                for path in backup_dir.glob("alex-*.db")
            )

            self.assertEqual(
                remaining,
                [
                    "alex-20260721T000000000000Z.db",
                    "alex-20260722T000000000000Z.db",
                ],
            )

            self.assertEqual(len(removed), 2)
            self.assertTrue(unrelated.exists())

    def test_missing_database_fails_without_creating_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "missing.db"

            with self.assertRaises(FileNotFoundError):
                run_scheduled_backup(
                    database_path=database,
                    backup_dir=root / "backups",
                )

            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()

