from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from alex_store import AlexStore


class AlexStoreTests(unittest.TestCase):
    def test_migration_is_idempotent_and_records_are_durable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AlexStore(
                Path(directory) / "alex.db"
            )

            store.migrate()
            store.migrate()

            self.assertEqual(
                store.health()["schema_version"],
                3,
            )

            store.put_record(
                "scenes",
                "study",
                {
                    "name": "Study",
                    "safety_level": "safe",
                },
            )

            self.assertEqual(
                store.records("scenes")[0]["name"],
                "Study",
            )

            details = {
                "node": "esp01",
                "capability": "relay_1",
                "action": "on",
                "status": "restricted",
                "risk": "restricted",
                "reason": "restricted_capability",
            }

            store.add_audit(
                "safety_denial",
                "verified",
                "warning",
                details=details,
            )

            audit = store.recent_audit(1)[0]

            self.assertEqual(
                audit["source"],
                "local_software",
            )

            self.assertEqual(
                audit["details"],
                details,
            )

    def test_command_source_and_backup_are_preserved(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            store.put_command(
                {
                    "command_id": "cmd-1",
                    "target": "demo",
                    "action": "inspect",
                    "payload": {},
                    "phase": "confirmed",
                    "source": "simulated",
                    "requested_at": (
                        "2026-01-01T00:00:00+00:00"
                    ),
                    "acknowledged_at": (
                        "2026-01-01T00:00:01+00:00"
                    ),
                    "failure_reason": None,
                }
            )

            backup = store.backup(
                root / "backups" / "alex.db"
            )

            self.assertTrue(
                backup.is_file()
            )

            self.assertGreater(
                backup.stat().st_size,
                0,
            )

            temporary = backup.with_name(
                f".{backup.name}.tmp"
            )

            self.assertFalse(
                temporary.exists()
            )

            db = sqlite3.connect(backup)

            try:
                integrity = db.execute(
                    "PRAGMA quick_check"
                ).fetchone()

                command = db.execute(
                    """
                    SELECT source, phase
                    FROM commands
                    WHERE command_id=?
                    """,
                    ("cmd-1",),
                ).fetchone()

            finally:
                db.close()

            self.assertIsNotNone(integrity)

            self.assertEqual(
                integrity[0],
                "ok",
            )

            self.assertEqual(
                command,
                ("simulated", "confirmed"),
            )

    def test_backup_replaces_existing_snapshot_with_latest_data(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            destination = (
                root
                / "backups"
                / "alex.db"
            )

            store.put_record(
                "scenes",
                "study",
                {
                    "name": "Study V1",
                },
            )

            store.backup(destination)

            store.put_record(
                "scenes",
                "study",
                {
                    "name": "Study V2",
                },
            )

            store.backup(destination)

            backup_store = AlexStore(
                destination
            )

            record = backup_store.get_record(
                "scenes",
                "study",
            )

            self.assertIsNotNone(record)

            self.assertEqual(
                record["name"],
                "Study V2",
            )

    def test_backup_rejects_live_database_as_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            store = AlexStore(
                root / "alex.db"
            )

            store.migrate()

            with self.assertRaisesRegex(
                ValueError,
                "must differ from the live database",
            ):
                store.backup(
                    store.path
                )

            self.assertEqual(
                store.health()["state"],
                "online",
            )


if __name__ == "__main__":
    unittest.main()
