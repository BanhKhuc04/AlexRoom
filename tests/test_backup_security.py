import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from alex_restore import create_emergency_copy
from alex_scheduled_backup import create_verified_backup


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permissions required",
)
def test_scheduled_backup_is_private():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        source = root / "source.db"
        destination = (
            root
            / "backups"
            / "backup.db"
        )

        connection = sqlite3.connect(source)

        try:
            connection.execute(
                "CREATE TABLE test(id INTEGER)"
            )
            connection.commit()
        finally:
            connection.close()

        create_verified_backup(
            source,
            destination,
        )

        assert (
            destination.stat().st_mode
            & 0o777
        ) == 0o600

        assert (
            destination.parent.stat().st_mode
            & 0o777
        ) == 0o700


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permissions required",
)
def test_emergency_copy_is_private():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        database = root / "alex.db"
        recovery = root / "recovery"

        connection = sqlite3.connect(database)

        try:
            connection.execute(
                "CREATE TABLE test(id INTEGER)"
            )
            connection.commit()
        finally:
            connection.close()

        emergency = create_emergency_copy(
            database,
            recovery,
        )

        assert emergency is not None

        assert (
            emergency.stat().st_mode
            & 0o777
        ) == 0o600

        assert (
            recovery.stat().st_mode
            & 0o777
        ) == 0o700
