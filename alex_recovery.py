from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from alex_health import (
    STATUS_CRITICAL,
    build_health_report,
    write_report_atomic,
)
from alex_restore import (
    find_latest_backup,
    restore_database,
    sqlite_integrity,
)


class RecoveryError(RuntimeError):
    pass


def run_systemctl(
    action: str,
    service: str,
) -> subprocess.CompletedProcess[str]:

    return subprocess.run(
        [
            "systemctl",
            action,
            service,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def service_is_active(
    service: str,
) -> bool:

    result = run_systemctl(
        "is-active",
        service,
    )

    return (
        result.returncode == 0
        and result.stdout.strip() == "active"
    )


def stop_service(
    service: str,
) -> None:

    result = run_systemctl(
        "stop",
        service,
    )

    if result.returncode != 0:
        raise RecoveryError(
            "service_stop_failed:"
            f"{service}:"
            f"{result.stderr.strip()}"
        )


def start_service(
    service: str,
) -> None:

    result = run_systemctl(
        "start",
        service,
    )

    if result.returncode != 0:
        raise RecoveryError(
            "service_start_failed:"
            f"{service}:"
            f"{result.stderr.strip()}"
        )


def wait_for_service(
    service: str,
    timeout_seconds: float = 20.0,
    interval_seconds: float = 0.5,
) -> None:

    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    while time.monotonic() < deadline:
        if service_is_active(service):
            return

        time.sleep(interval_seconds)

    raise RecoveryError(
        f"service_did_not_become_active:{service}"
    )


def require_root() -> None:
    if (
        os.name != "nt"
        and hasattr(os, "geteuid")
        and os.geteuid() != 0
    ):
        raise PermissionError(
            "recovery_requires_root"
        )


def choose_backup(
    backup_path: Path | None,
    backup_dir: Path,
) -> Path:

    if backup_path is not None:
        chosen = backup_path.expanduser().resolve()
    else:
        chosen = find_latest_backup(
            backup_dir
        )

    valid, detail = sqlite_integrity(
        chosen
    )

    if not valid:
        raise RecoveryError(
            f"backup_integrity_failed:{detail}"
        )

    return chosen


def run_recovery(
    database_path: Path,
    backup_dir: Path,
    recovery_dir: Path,
    health_output: Path,
    service_name: str = "alex-core.service",
    backup_path: Path | None = None,
) -> dict[str, Any]:

    database_path = (
        database_path
        .expanduser()
        .resolve()
    )

    backup_dir = (
        backup_dir
        .expanduser()
        .resolve()
    )

    recovery_dir = (
        recovery_dir
        .expanduser()
        .resolve()
    )

    health_output = (
        health_output
        .expanduser()
        .resolve()
    )

    # Validate backup BEFORE stopping production.
    chosen_backup = choose_backup(
        backup_path=backup_path,
        backup_dir=backup_dir,
    )

    service_was_active = service_is_active(
        service_name
    )

    service_stopped = False
    service_started = False

    try:
        if service_was_active:
            stop_service(
                service_name
            )
            service_stopped = True

        restore_result = restore_database(
            database_path=database_path,
            backup_path=chosen_backup,
            recovery_dir=recovery_dir,
        )

        start_service(
            service_name
        )
        service_started = True

        wait_for_service(
            service_name
        )

        restored_valid, restored_detail = (
            sqlite_integrity(
                database_path
            )
        )

        if not restored_valid:
            raise RecoveryError(
                "restored_database_invalid:"
                f"{restored_detail}"
            )

        report = build_health_report(
            database_path=database_path,
            backup_dir=backup_dir,
            disk_path=database_path.parent,
            service_name=service_name,
        )

        write_report_atomic(
            health_output,
            report,
        )

        if (
            report["checks"]["database"]["status"]
            == STATUS_CRITICAL
        ):
            raise RecoveryError(
                "database_health_critical"
            )

        if (
            report["checks"]["core_service"]["status"]
            == STATUS_CRITICAL
        ):
            raise RecoveryError(
                "core_service_health_critical"
            )

        return {
            "status": "recovered",
            "database": str(
                database_path
            ),
            "backup": str(
                chosen_backup
            ),
            "emergency_copy": (
                restore_result[
                    "emergency_copy"
                ]
            ),
            "integrity": (
                restored_detail
            ),
            "health": report["status"],
            "service": service_name,
        }

    except Exception:
        # Best-effort service recovery.
        if (
            service_was_active
            and service_stopped
            and not service_started
        ):
            try:
                start_service(
                    service_name
                )
            except Exception:
                pass

        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "ALEX controlled database recovery"
        )
    )

    parser.add_argument(
        "--database",
        default="/var/lib/alex/alex.db",
    )

    parser.add_argument(
        "--backup-dir",
        default="/var/lib/alex/backups",
    )

    parser.add_argument(
        "--backup",
        default=None,
    )

    parser.add_argument(
        "--latest",
        action="store_true",
    )

    parser.add_argument(
        "--recovery-dir",
        default="/var/lib/alex/recovery",
    )

    parser.add_argument(
        "--health-output",
        default=(
            "/var/lib/alex/health/"
            "health.json"
        ),
    )

    parser.add_argument(
        "--service",
        default="alex-core.service",
    )

    args = parser.parse_args()

    if (
        not args.latest
        and args.backup is None
    ):
        parser.error(
            "use --latest or --backup PATH"
        )

    try:
        require_root()

        result = run_recovery(
            database_path=Path(
                args.database
            ),
            backup_dir=Path(
                args.backup_dir
            ),
            backup_path=(
                Path(args.backup)
                if args.backup
                else None
            ),
            recovery_dir=Path(
                args.recovery_dir
            ),
            health_output=Path(
                args.health_output
            ),
            service_name=args.service,
        )

    except Exception as exc:
        print(
            f"RECOVERY_FAILED {exc}",
            flush=True,
        )
        return 1

    print(
        "RECOVERY_OK "
        + json.dumps(
            result,
            ensure_ascii=False,
        ),
        flush=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
