from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from alex_backup import BackupService
from alex_store import AlexStore

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

sys.path.insert(
    0,
    str(SCRIPTS),
)

import restore_production


class FakeService:
    def __init__(self) -> None:
        self.active = True
        self.actions = []

    def systemctl(
        self,
        action: str,
        service: str,
    ) -> None:
        self.actions.append(
            (action, service)
        )

        if action == "stop":
            self.active = False

        elif action == "start":
            self.active = True

    def checker(
        self,
        service: str,
    ) -> bool:
        return self.active


class ProductionRestoreTests(
    unittest.TestCase
):
    def make_environment(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)

        database = root / "alex.db"

        store = AlexStore(database)
        store.migrate()

        backups = root / "backups"
        rollbacks = root / "rollback"

        backup_service = BackupService(
            store,
            backups,
            retention=5,
        )

        return (
            temp,
            store,
            database,
            backups,
            rollbacks,
            backup_service,
        )

    def test_confirmation_is_required(
        self,
    ) -> None:
        (
            temp,
            store,
            database,
            backups,
            rollbacks,
            backup_service,
        ) = self.make_environment()

        with temp:
            backup = backup_service.create()

            with self.assertRaisesRegex(
                PermissionError,
                "RESTORE-PRODUCTION",
            ):
                restore_production.production_restore(
                    filename=backup["file"],
                    confirmation="NO",
                    database=database,
                    backup_dir=backups,
                    rollback_dir=rollbacks,
                )

    def test_successful_restore_restarts_service_and_health(
        self,
    ) -> None:
        (
            temp,
            store,
            database,
            backups,
            rollbacks,
            backup_service,
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

            fake = FakeService()

            result = (
                restore_production.production_restore(
                    filename=backup["file"],
                    confirmation="RESTORE-PRODUCTION",
                    database=database,
                    backup_dir=backups,
                    rollback_dir=rollbacks,
                    systemctl=fake.systemctl,
                    state_checker=fake.checker,
                    health_waiter=lambda _: {
                        "api": "online",
                        "mqtt": "connected",
                        "device": "online",
                    },
                )
            )

            self.assertTrue(
                result["restored"]
            )

            self.assertFalse(
                result[
                    "automatic_rollback"
                ]
            )

            self.assertEqual(
                fake.actions,
                [
                    ("stop", "alex-core"),
                    ("start", "alex-core"),
                ],
            )

            restored = AlexStore(
                database
            ).get_record(
                "settings",
                "demo",
            )

            self.assertEqual(
                restored["value"],
                "before",
            )

    def test_failed_health_triggers_automatic_rollback(
        self,
    ) -> None:
        (
            temp,
            store,
            database,
            backups,
            rollbacks,
            backup_service,
        ) = self.make_environment()

        with temp:
            store.put_record(
                "settings",
                "demo",
                {"value": "backup-state"},
            )

            backup = backup_service.create()

            store.put_record(
                "settings",
                "demo",
                {"value": "production-state"},
            )

            fake = FakeService()
            calls = {"count": 0}

            def health_waiter(_):
                calls["count"] += 1

                if calls["count"] == 1:
                    raise RuntimeError(
                        "simulated bad restored health"
                    )

                return {
                    "api": "online",
                    "mqtt": "connected",
                    "device": "online",
                }

            with self.assertRaisesRegex(
                RuntimeError,
                "automatic rollback completed",
            ):
                restore_production.production_restore(
                    filename=backup["file"],
                    confirmation="RESTORE-PRODUCTION",
                    database=database,
                    backup_dir=backups,
                    rollback_dir=rollbacks,
                    systemctl=fake.systemctl,
                    state_checker=fake.checker,
                    health_waiter=health_waiter,
                )

            current = AlexStore(
                database
            ).get_record(
                "settings",
                "demo",
            )

            self.assertEqual(
                current["value"],
                "production-state",
            )

            self.assertEqual(
                fake.actions,
                [
                    ("stop", "alex-core"),
                    ("start", "alex-core"),
                    ("stop", "alex-core"),
                    ("start", "alex-core"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
