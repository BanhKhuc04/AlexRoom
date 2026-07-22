import sqlite3
import tempfile
from pathlib import Path

import pytest

import alex_recovery
from alex_recovery import (
    RecoveryError,
    choose_backup,
    run_recovery,
)


def create_db(
    path: Path,
    value: str,
) -> None:

    connection = sqlite3.connect(
        path
    )

    try:
        connection.execute(
            "CREATE TABLE state "
            "(value TEXT)"
        )

        connection.execute(
            "INSERT INTO state(value) "
            "VALUES (?)",
            (value,),
        )

        connection.commit()

    finally:
        connection.close()


def read_value(
    path: Path,
) -> str:

    connection = sqlite3.connect(
        path
    )

    try:
        row = connection.execute(
            "SELECT value FROM state"
        ).fetchone()

        return row[0]

    finally:
        connection.close()


def test_choose_backup_rejects_corrupt_file():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        backup = (
            root
            / "alex-corrupt.db"
        )

        backup.write_bytes(
            b"not sqlite"
        )

        with pytest.raises(
            RecoveryError,
            match="backup_integrity_failed",
        ):
            choose_backup(
                backup_path=backup,
                backup_dir=root,
            )


def test_recovery_restores_and_restarts_service(
    monkeypatch,
):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"

        backup_dir = (
            root
            / "backups"
        )

        backup_dir.mkdir()

        backup = (
            backup_dir
            / "alex-test.db"
        )

        recovery_dir = (
            root
            / "recovery"
        )

        health_output = (
            root
            / "health"
            / "health.json"
        )

        create_db(
            database,
            "current-data",
        )

        create_db(
            backup,
            "backup-data",
        )

        actions = []

        monkeypatch.setattr(
            alex_recovery,
            "service_is_active",
            lambda service: True,
        )

        monkeypatch.setattr(
            alex_recovery,
            "stop_service",
            lambda service: (
                actions.append(
                    ("stop", service)
                )
            ),
        )

        monkeypatch.setattr(
            alex_recovery,
            "start_service",
            lambda service: (
                actions.append(
                    ("start", service)
                )
            ),
        )

        monkeypatch.setattr(
            alex_recovery,
            "wait_for_service",
            lambda service: None,
        )

        monkeypatch.setattr(
            alex_recovery,
            "build_health_report",
            lambda **kwargs: {
                "status": "healthy",
                "checks": {
                    "database": {
                        "status": "healthy",
                    },
                    "core_service": {
                        "status": "healthy",
                    },
                },
            },
        )

        result = run_recovery(
            database_path=database,
            backup_dir=backup_dir,
            backup_path=backup,
            recovery_dir=recovery_dir,
            health_output=health_output,
            service_name=(
                "alex-core.service"
            ),
        )

        assert (
            read_value(database)
            == "backup-data"
        )

        emergency = Path(
            result["emergency_copy"]
        )

        assert emergency.is_file()

        assert (
            read_value(emergency)
            == "current-data"
        )

        assert actions == [
            (
                "stop",
                "alex-core.service",
            ),
            (
                "start",
                "alex-core.service",
            ),
        ]

        assert result["status"] == (
            "recovered"
        )

        assert result["integrity"] == (
            "ok"
        )

        assert health_output.is_file()


def test_restore_failure_restarts_original_service(
    monkeypatch,
):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"

        backup = root / "alex-test.db"

        create_db(
            database,
            "current",
        )

        create_db(
            backup,
            "backup",
        )

        actions = []

        monkeypatch.setattr(
            alex_recovery,
            "service_is_active",
            lambda service: True,
        )

        monkeypatch.setattr(
            alex_recovery,
            "stop_service",
            lambda service: (
                actions.append(
                    ("stop", service)
                )
            ),
        )

        monkeypatch.setattr(
            alex_recovery,
            "start_service",
            lambda service: (
                actions.append(
                    ("start", service)
                )
            ),
        )

        monkeypatch.setattr(
            alex_recovery,
            "restore_database",
            lambda **kwargs: (
                (_ for _ in ()).throw(
                    RuntimeError(
                        "simulated_restore_failure"
                    )
                )
            ),
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "simulated_restore_failure"
            ),
        ):
            run_recovery(
                database_path=database,
                backup_dir=root,
                backup_path=backup,
                recovery_dir=(
                    root / "recovery"
                ),
                health_output=(
                    root
                    / "health.json"
                ),
            )

        assert actions == [
            (
                "stop",
                "alex-core.service",
            ),
            (
                "start",
                "alex-core.service",
            ),
        ]


def test_invalid_backup_does_not_stop_service(
    monkeypatch,
):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"

        corrupt = (
            root
            / "alex-corrupt.db"
        )

        create_db(
            database,
            "production",
        )

        corrupt.write_bytes(
            b"corrupt"
        )

        called = []

        monkeypatch.setattr(
            alex_recovery,
            "stop_service",
            lambda service: (
                called.append(service)
            ),
        )

        with pytest.raises(
            RecoveryError,
            match="backup_integrity_failed",
        ):
            run_recovery(
                database_path=database,
                backup_dir=root,
                backup_path=corrupt,
                recovery_dir=(
                    root / "recovery"
                ),
                health_output=(
                    root / "health.json"
                ),
            )

        assert called == []

        assert (
            read_value(database)
            == "production"
        )
