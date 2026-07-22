from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_KEEP_COUNT = 14


def backup_filename(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    current = current.astimezone(timezone.utc)

    return f"alex-{current.strftime('%Y%m%dT%H%M%S%fZ')}.db"


def create_verified_backup(
    database_path: Path,
    destination: Path,
) -> Path:
    """Create a transactionally consistent SQLite backup."""

    database_path = database_path.expanduser().resolve()
    destination = destination.expanduser().resolve()

    if not database_path.is_file():
        raise FileNotFoundError(
            f"database_not_found:{database_path}"
        )

    if database_path.stat().st_size <= 0:
        raise RuntimeError(
            f"database_empty:{database_path}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_name(
        destination.name + ".tmp"
    )

    temporary.unlink(missing_ok=True)

    source = None
    target = None

    try:
        source = sqlite3.connect(database_path)
        target = sqlite3.connect(temporary)

        # SQLite online backup API:
        # safe even when source database is active/WAL.
        source.backup(target)
        target.commit()

        result = target.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if result is None or result[0] != "ok":
            raise RuntimeError(
                "sqlite_backup_integrity_check_failed"
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

    temporary.replace(destination)

    return destination


def prune_backups(
    backup_dir: Path,
    keep_count: int,
) -> list[Path]:

    if keep_count < 1:
        raise ValueError(
            "keep_count_must_be_positive"
        )

    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    backups = sorted(
        (
            path
            for path in backup_dir.glob("alex-*.db")
            if path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )

    removed: list[Path] = []

    for stale in backups[keep_count:]:
        stale.unlink()
        removed.append(stale)

    return removed


def run_scheduled_backup(
    database_path: Path,
    backup_dir: Path | None = None,
    keep_count: int = DEFAULT_KEEP_COUNT,
    now: datetime | None = None,
) -> Path:

    database_path = database_path.expanduser().resolve()

    if backup_dir is None:
        backup_dir = database_path.parent / "backups"

    backup_dir = backup_dir.expanduser().resolve()

    destination = backup_dir / backup_filename(now)

    created = create_verified_backup(
        database_path=database_path,
        destination=destination,
    )

    prune_backups(
        backup_dir=backup_dir,
        keep_count=keep_count,
    )

    return created


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ALEX verified scheduled SQLite backup"
    )

    parser.add_argument(
        "--database",
        default=os.getenv(
            "ALEX_DATABASE_PATH",
            "data/alex.db",
        ),
    )

    parser.add_argument(
        "--backup-dir",
        default=os.getenv(
            "ALEX_BACKUP_DIR"
        ),
    )

    parser.add_argument(
        "--keep",
        type=int,
        default=int(
            os.getenv(
                "ALEX_BACKUP_KEEP",
                str(DEFAULT_KEEP_COUNT),
            )
        ),
    )

    args = parser.parse_args()

    try:
        created = run_scheduled_backup(
            database_path=Path(args.database),
            backup_dir=(
                Path(args.backup_dir)
                if args.backup_dir
                else None
            ),
            keep_count=args.keep,
        )
    except Exception as exc:
        print(
            f"BACKUP_FAILED {exc}",
            flush=True,
        )
        return 1

    print(
        f"BACKUP_OK {created}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
