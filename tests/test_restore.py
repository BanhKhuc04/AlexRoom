import sqlite3
import tempfile
from pathlib import Path

import pytest

from alex_restore import (
    find_latest_backup,
    restore_database,
    sqlite_integrity,
)


def create_database(
    path: Path,
    value: str,
) -> None:
    connection = sqlite3.connect(path)

    try:
        connection.execute(
            "CREATE TABLE state (value TEXT)"
        )

        connection.execute(
            "INSERT INTO state(value) VALUES (?)",
            (value,),
        )

        connection.commit()
    finally:
        connection.close()


def read_value(path: Path) -> str:
    connection = sqlite3.connect(path)

    try:
        row = connection.execute(
            "SELECT value FROM state"
        ).fetchone()
    finally:
        connection.close()

    return row[0]


def test_valid_database_integrity():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "alex.db"

        create_database(
            database,
            "healthy",
        )

        valid, detail = sqlite_integrity(database)

        assert valid is True
        assert detail == "ok"


def test_restore_replaces_database_content():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"
        backup = root / "backup.db"
        recovery = root / "recovery"

        create_database(
            database,
            "current",
        )

        create_database(
            backup,
            "backup",
        )

        result = restore_database(
            database_path=database,
            backup_path=backup,
            recovery_dir=recovery,
        )

        assert result["status"] == "restored"
        assert result["integrity"] == "ok"

        assert read_value(database) == "backup"


def test_restore_preserves_pre_restore_database():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"
        backup = root / "backup.db"
        recovery = root / "recovery"

        create_database(
            database,
            "important-current-data",
        )

        create_database(
            backup,
            "older-backup-data",
        )

        result = restore_database(
            database_path=database,
            backup_path=backup,
            recovery_dir=recovery,
        )

        emergency = Path(
            result["emergency_copy"]
        )

        assert emergency.is_file()

        assert (
            read_value(emergency)
            == "important-current-data"
        )

        assert (
            read_value(database)
            == "older-backup-data"
        )


def test_corrupt_backup_is_rejected_without_touching_database():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"
        backup = root / "corrupt.db"

        create_database(
            database,
            "keep-me",
        )

        backup.write_bytes(
            b"this is not sqlite"
        )

        with pytest.raises(
            RuntimeError,
            match="backup_integrity_failed",
        ):
            restore_database(
                database_path=database,
                backup_path=backup,
                recovery_dir=root / "recovery",
            )

        assert read_value(database) == "keep-me"

        assert not (
            root
            / "alex.db.restore.tmp"
        ).exists()


def test_restore_works_when_database_is_missing():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"
        backup = root / "backup.db"

        create_database(
            backup,
            "recovered",
        )

        result = restore_database(
            database_path=database,
            backup_path=backup,
            recovery_dir=root / "recovery",
        )

        assert result["emergency_copy"] is None
        assert read_value(database) == "recovered"


def test_find_latest_backup():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        old = root / "alex-20260720.db"
        newest = root / "alex-20260722.db"

        old.write_bytes(b"old")
        newest.write_bytes(b"new")

        old.touch()

        import os

        os.utime(
            old,
            (1000, 1000),
        )

        os.utime(
            newest,
            (2000, 2000),
        )

        assert find_latest_backup(root) == newest
