import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alex_health import (
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_WARNING,
    check_backup,
    check_database,
    overall_status,
    write_report_atomic,
)


def test_database_healthy():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "alex.db"

        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE test (id INTEGER PRIMARY KEY)"
            )
            connection.commit()
        finally:
            connection.close()

        result = check_database(database)

        assert result["status"] == STATUS_HEALTHY
        assert result["message"] == "database_ok"


def test_missing_database_is_critical():
    with tempfile.TemporaryDirectory() as directory:
        result = check_database(
            Path(directory) / "missing.db"
        )

        assert result["status"] == STATUS_CRITICAL


def test_recent_backup_is_healthy():
    with tempfile.TemporaryDirectory() as directory:
        backup_dir = Path(directory)
        backup = backup_dir / "alex-test.db"
        backup.write_bytes(b"backup")

        now = datetime.now(timezone.utc)

        os.utime(
            backup,
            (
                now.timestamp(),
                now.timestamp(),
            ),
        )

        result = check_backup(
            backup_dir,
            now=now,
        )

        assert result["status"] == STATUS_HEALTHY


def test_old_backup_is_critical():
    with tempfile.TemporaryDirectory() as directory:
        backup_dir = Path(directory)
        backup = backup_dir / "alex-old.db"
        backup.write_bytes(b"backup")

        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=72)

        os.utime(
            backup,
            (
                old.timestamp(),
                old.timestamp(),
            ),
        )

        result = check_backup(
            backup_dir,
            now=now,
        )

        assert result["status"] == STATUS_CRITICAL


def test_overall_warning():
    checks = {
        "database": {"status": STATUS_HEALTHY},
        "disk": {"status": STATUS_WARNING},
        "backup": {"status": STATUS_HEALTHY},
    }

    assert overall_status(checks) == STATUS_WARNING


def test_atomic_report_write():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "health" / "health.json"

        write_report_atomic(
            output,
            {
                "status": STATUS_HEALTHY,
            },
        )

        assert output.is_file()
        assert '"healthy"' in output.read_text(
            encoding="utf-8"
        )
        assert not Path(
            str(output) + ".tmp"
        ).exists()
