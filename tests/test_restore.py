from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alex_backup import BackupService
from alex_restore import RestoreService
from alex_store import AlexStore


class RestoreServiceTests(
    unittest.TestCase
):
    def make_environment(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)

        store = AlexStore(
            root / "alex.db"
        )

        store.migrate()

        backup_service = BackupService(
            store,
            root / "backups",
            retention=10,
        )

        restore_service = RestoreService(
            store,
            root / "backups",
            root / "rollback",
        )

        return (
            temp,
            store,
            backup_service,
            restore_service,
        )

    def test_validate_good_backup(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            backup = backup_service.create()

            result = restore_service.validate(
                backup["file"]
            )

            self.assertTrue(
                result["validated"]
            )

            self.assertEqual(
                result["integrity"],
                "ok",
            )

    def test_restore_requires_confirmation(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            backup = backup_service.create()

            with self.assertRaisesRegex(
                PermissionError,
                "RESTORE",
            ):
                restore_service.restore(
                    backup["file"],
                    confirmation="NO",
                    service_stopped=True,
                )

    def test_restore_requires_service_stopped(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            backup = backup_service.create()

            with self.assertRaisesRegex(
                RuntimeError,
                "must be stopped",
            ):
                restore_service.restore(
                    backup["file"],
                    confirmation="RESTORE",
                    service_stopped=False,
                )

    def test_restore_recovers_old_database_state(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            store.put_record(
                "settings",
                "demo",
                {"value": "before"},
            )

            backup = backup_service.create()

            store.put_record(
                "settings",
                "demo",
                {"value": "after"},
            )

            self.assertEqual(
                store.get_record(
                    "settings",
                    "demo",
                )["value"],
                "after",
            )

            result = restore_service.restore(
                backup["file"],
                confirmation="RESTORE",
                service_stopped=True,
            )

            restored = store.get_record(
                "settings",
                "demo",
            )

            self.assertTrue(
                result["restored"]
            )

            self.assertEqual(
                restored["value"],
                "before",
            )

            rollback = (
                restore_service.rollback_dir
                / result["rollback_file"]
            )

            self.assertTrue(
                rollback.is_file()
            )

    def test_modified_backup_fails_sha256_validation(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            backup = backup_service.create()

            path = (
                backup_service.backup_dir
                / backup["file"]
            )

            with path.open("ab") as stream:
                stream.write(
                    b"tampered"
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "SHA256 mismatch",
            ):
                restore_service.validate(
                    backup["file"]
                )

    def test_path_traversal_is_rejected(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            with self.assertRaisesRegex(
                ValueError,
                "Invalid backup filename",
            ):
                restore_service.validate(
                    "../alex-evil.db"
                )


    def test_explicit_rollback_restores_pre_restore_snapshot(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            store.put_record(
                "settings",
                "demo",
                {"value": "original"},
            )

            backup = backup_service.create()

            store.put_record(
                "settings",
                "demo",
                {"value": "newer"},
            )

            restored = restore_service.restore(
                backup["file"],
                confirmation="RESTORE",
                service_stopped=True,
            )

            self.assertEqual(
                store.get_record(
                    "settings",
                    "demo",
                )["value"],
                "original",
            )

            rollback = (
                restore_service.restore_rollback(
                    restored["rollback_file"],
                    confirmation="ROLLBACK",
                    service_stopped=True,
                )
            )

            self.assertTrue(
                rollback["rolled_back"]
            )

            self.assertEqual(
                store.get_record(
                    "settings",
                    "demo",
                )["value"],
                "newer",
            )

    def test_rollback_requires_service_stopped(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            store.put_record(
                "settings",
                "demo",
                {"value": "before"},
            )

            backup = backup_service.create()

            result = restore_service.restore(
                backup["file"],
                confirmation="RESTORE",
                service_stopped=True,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "must be stopped",
            ):
                restore_service.restore_rollback(
                    result["rollback_file"],
                    confirmation="ROLLBACK",
                    service_stopped=False,
                )

    def test_rollback_requires_confirmation(
        self,
    ) -> None:
        (
            temp,
            store,
            backup_service,
            restore_service,
        ) = self.make_environment()

        with temp:
            with self.assertRaisesRegex(
                PermissionError,
                "ROLLBACK",
            ):
                restore_service.restore_rollback(
                    "pre-restore-demo.db",
                    confirmation="NO",
                    service_stopped=True,
                )


if __name__ == "__main__":
    unittest.main()
