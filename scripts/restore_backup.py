from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alex_restore import RestoreService
from alex_store import AlexStore


def resolve_paths(
    env: Mapping[str, str] | None = None,
) -> tuple[Path, Path, Path]:
    values = os.environ if env is None else env

    database = Path(
        values.get(
            "ALEX_DATABASE_PATH",
            str(ROOT / "data" / "alex.db"),
        )
    )

    backup_dir = Path(
        values.get(
            "ALEX_BACKUP_DIR",
            str(database.parent / "backups"),
        )
    )

    rollback_dir = Path(
        values.get(
            "ALEX_RESTORE_ROLLBACK_DIR",
            str(
                database.parent
                / "restore-rollback"
            ),
        )
    )

    return (
        database,
        backup_dir,
        rollback_dir,
    )


def service_is_active(
    service_name: str,
) -> bool:
    try:
        result = subprocess.run(
            [
                "systemctl",
                "is-active",
                service_name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    except FileNotFoundError as exc:
        raise RuntimeError(
            "systemctl is unavailable"
        ) from exc

    state = result.stdout.strip()

    return state == "active"


def build_restore_service(
    *,
    database: Path,
    backup_dir: Path,
    rollback_dir: Path,
) -> RestoreService:
    store = AlexStore(database)

    return RestoreService(
        store,
        backup_dir,
        rollback_dir,
    )


def validate_backup(
    filename: str,
    *,
    database: Path,
    backup_dir: Path,
    rollback_dir: Path,
) -> dict:
    service = build_restore_service(
        database=database,
        backup_dir=backup_dir,
        rollback_dir=rollback_dir,
    )

    return service.validate(filename)


def restore_backup(
    filename: str,
    *,
    confirmation: str,
    database: Path,
    backup_dir: Path,
    rollback_dir: Path,
    service_name: str = "alex-core",
    service_checker: Callable[
        [str],
        bool,
    ] = service_is_active,
) -> dict:
    if confirmation != "RESTORE":
        raise PermissionError(
            "Restore confirmation must be RESTORE"
        )

    if service_checker(service_name):
        raise RuntimeError(
            f"{service_name} is active; "
            "stop the service before restore"
        )

    service = build_restore_service(
        database=database,
        backup_dir=backup_dir,
        rollback_dir=rollback_dir,
    )

    return service.restore(
        filename,
        confirmation=confirmation,
        service_stopped=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or restore an ALEX "
            "SQLite backup."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    validate_parser = (
        subparsers.add_parser(
            "validate",
            help=(
                "Validate checksum and SQLite "
                "integrity without changing data."
            ),
        )
    )

    validate_parser.add_argument(
        "filename",
    )

    restore_parser = (
        subparsers.add_parser(
            "restore",
            help=(
                "Restore a validated backup. "
                "alex-core must already be stopped."
            ),
        )
    )

    restore_parser.add_argument(
        "filename",
    )

    restore_parser.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly RESTORE.",
    )

    restore_parser.add_argument(
        "--service",
        default="alex-core",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    database, backup_dir, rollback_dir = (
        resolve_paths()
    )

    try:
        if args.command == "validate":
            result = validate_backup(
                args.filename,
                database=database,
                backup_dir=backup_dir,
                rollback_dir=rollback_dir,
            )

        elif args.command == "restore":
            result = restore_backup(
                args.filename,
                confirmation=args.confirm,
                database=database,
                backup_dir=backup_dir,
                rollback_dir=rollback_dir,
                service_name=args.service,
            )

        else:
            raise RuntimeError(
                "Unsupported command"
            )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        return 0

    except (
        FileNotFoundError,
        PermissionError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
