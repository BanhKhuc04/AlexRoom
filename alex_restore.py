from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )


def sqlite_integrity(path: Path) -> tuple[bool, str]:
    path = path.expanduser().resolve()

    if not path.is_file():
        return False, "file_not_found"

    if path.stat().st_size <= 0:
        return False, "file_empty"

    connection = None

    try:
        connection = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=5,
        )

        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if result is None:
            return False, "integrity_check_no_result"

        if result[0] != "ok":
            return False, str(result[0])

        return True, "ok"

    except sqlite3.Error as exc:
        return False, str(exc)

    finally:
        if connection is not None:
            connection.close()


def find_latest_backup(backup_dir: Path) -> Path:
    backup_dir = backup_dir.expanduser().resolve()

    if not backup_dir.is_dir():
        raise FileNotFoundError(
            f"backup_directory_not_found:{backup_dir}"
        )

    backups = [
        path
        for path in backup_dir.glob("alex-*.db")
        if path.is_file()
    ]

    if not backups:
        raise FileNotFoundError(
            f"backup_not_found:{backup_dir}"
        )

    return max(
        backups,
        key=lambda path: path.stat().st_mtime,
    )


def create_emergency_copy(
    database_path: Path,
    recovery_dir: Path,
) -> Path | None:
    database_path = database_path.expanduser().resolve()
    recovery_dir = recovery_dir.expanduser().resolve()

    if not database_path.exists():
        return None

    recovery_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        recovery_dir
        / f"alex-pre-restore-{utc_stamp()}.db"
    )

    shutil.copy2(
        database_path,
        destination,
    )

    return destination


def restore_database(
    database_path: Path,
    backup_path: Path,
    recovery_dir: Path | None = None,
) -> dict[str, Any]:

    database_path = database_path.expanduser().resolve()
    backup_path = backup_path.expanduser().resolve()

    if database_path == backup_path:
        raise ValueError(
            "backup_and_database_must_differ"
        )

    valid, detail = sqlite_integrity(backup_path)

    if not valid:
        raise RuntimeError(
            f"backup_integrity_failed:{detail}"
        )

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if recovery_dir is None:
        recovery_dir = (
            database_path.parent
            / "recovery"
        )

    recovery_dir = recovery_dir.expanduser().resolve()

    emergency_copy = create_emergency_copy(
        database_path,
        recovery_dir,
    )

    temporary = database_path.with_name(
        database_path.name + ".restore.tmp"
    )

    temporary.unlink(missing_ok=True)

    previous_mode = None
    previous_uid = None
    previous_gid = None

    if database_path.exists():
        database_stat = database_path.stat()

        previous_mode = (
            database_stat.st_mode & 0o777
        )

        previous_uid = getattr(
            database_stat,
            "st_uid",
            None,
        )

        previous_gid = getattr(
            database_stat,
            "st_gid",
            None,
        )

    source = None
    target = None

    try:
        source = sqlite3.connect(
            f"file:{backup_path}?mode=ro",
            uri=True,
            timeout=5,
        )

        target = sqlite3.connect(temporary)

        source.backup(target)
        target.commit()

        result = target.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if result is None or result[0] != "ok":
            raise RuntimeError(
                "restored_database_integrity_failed"
            )

    except Exception:
        if target is not None:
            target.close()
            target = None

        if source is not None:
            source.close()
            source = None

        temporary.unlink(missing_ok=True)
        raise

    finally:
        if target is not None:
            target.close()

        if source is not None:
            source.close()

    if previous_mode is not None:
        os.chmod(
            temporary,
            previous_mode,
        )

    # A production recovery may run as root. Preserve the
    # ownership of alex.db so alex-core can reopen it.
    if (
        previous_uid is not None
        and previous_gid is not None
        and hasattr(os, "chown")
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    ):
        os.chown(
            temporary,
            previous_uid,
            previous_gid,
        )

    temporary.replace(database_path)

    valid_restored, restored_detail = sqlite_integrity(
        database_path
    )

    if not valid_restored:
        raise RuntimeError(
            "post_restore_integrity_failed:"
            f"{restored_detail}"
        )

    return {
        "status": "restored",
        "database": str(database_path),
        "backup": str(backup_path),
        "emergency_copy": (
            str(emergency_copy)
            if emergency_copy
            else None
        ),
        "integrity": restored_detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely restore the ALEX SQLite database"
    )

    parser.add_argument(
        "--database",
        default="/var/lib/alex/alex.db",
    )

    source = parser.add_mutually_exclusive_group(
        required=True
    )

    source.add_argument(
        "--backup",
        help="Specific backup database to restore",
    )

    source.add_argument(
        "--latest",
        action="store_true",
        help="Restore the newest alex-*.db backup",
    )

    parser.add_argument(
        "--backup-dir",
        default="/var/lib/alex/backups",
    )

    parser.add_argument(
        "--recovery-dir",
        default="/var/lib/alex/recovery",
    )

    args = parser.parse_args()

    try:
        if args.latest:
            backup_path = find_latest_backup(
                Path(args.backup_dir)
            )
        else:
            backup_path = Path(args.backup)

        result = restore_database(
            database_path=Path(args.database),
            backup_path=backup_path,
            recovery_dir=Path(args.recovery_dir),
        )

    except Exception as exc:
        print(
            f"RESTORE_FAILED {exc}",
            flush=True,
        )
        return 1

    print(
        "RESTORE_OK "
        f"database={result['database']} "
        f"backup={result['backup']} "
        f"emergency_copy={result['emergency_copy']} "
        f"integrity={result['integrity']}",
        flush=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
