from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_HEALTHY = "healthy"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"
STATUS_UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def check_database(database_path: Path) -> dict[str, Any]:
    database_path = database_path.expanduser().resolve()

    if not database_path.is_file():
        return {
            "status": STATUS_CRITICAL,
            "message": "database_not_found",
            "path": str(database_path),
        }

    if database_path.stat().st_size <= 0:
        return {
            "status": STATUS_CRITICAL,
            "message": "database_empty",
            "path": str(database_path),
        }

    connection = None

    try:
        connection = sqlite3.connect(
            f"file:{database_path}?mode=ro",
            uri=True,
            timeout=5,
        )

        result = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()

        if result is None or result[0] != "ok":
            return {
                "status": STATUS_CRITICAL,
                "message": "database_quick_check_failed",
                "detail": result[0] if result else None,
                "path": str(database_path),
            }

        return {
            "status": STATUS_HEALTHY,
            "message": "database_ok",
            "path": str(database_path),
            "size_bytes": database_path.stat().st_size,
        }

    except sqlite3.Error as exc:
        return {
            "status": STATUS_CRITICAL,
            "message": "database_error",
            "detail": str(exc),
            "path": str(database_path),
        }

    finally:
        if connection is not None:
            connection.close()


def check_disk(
    path: Path,
    warning_percent: float = 15.0,
    critical_percent: float = 5.0,
) -> dict[str, Any]:

    path = path.expanduser().resolve()

    usage = shutil.disk_usage(path)

    free_percent = (
        usage.free / usage.total * 100.0
        if usage.total
        else 0.0
    )

    if free_percent <= critical_percent:
        status = STATUS_CRITICAL
    elif free_percent <= warning_percent:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "disk_space",
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_percent": round(free_percent, 2),
    }


def check_backup(
    backup_dir: Path,
    now: datetime | None = None,
    warning_hours: float = 26.0,
    critical_hours: float = 48.0,
) -> dict[str, Any]:

    backup_dir = backup_dir.expanduser().resolve()
    current = now or utc_now()

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    if not backup_dir.is_dir():
        return {
            "status": STATUS_CRITICAL,
            "message": "backup_directory_not_found",
            "path": str(backup_dir),
        }

    backups = [
        path
        for path in backup_dir.glob("alex-*.db")
        if path.is_file()
    ]

    if not backups:
        return {
            "status": STATUS_CRITICAL,
            "message": "backup_not_found",
            "path": str(backup_dir),
        }

    latest = max(
        backups,
        key=lambda path: path.stat().st_mtime,
    )

    modified = datetime.fromtimestamp(
        latest.stat().st_mtime,
        tz=timezone.utc,
    )

    age_hours = (
        current.astimezone(timezone.utc) - modified
    ).total_seconds() / 3600.0

    if age_hours >= critical_hours:
        status = STATUS_CRITICAL
    elif age_hours >= warning_hours:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "backup_age",
        "latest_backup": str(latest),
        "age_hours": round(age_hours, 2),
        "size_bytes": latest.stat().st_size,
    }


def check_service(service_name: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": STATUS_UNKNOWN,
            "message": "service_check_unavailable",
            "service": service_name,
            "detail": str(exc),
        }

    state = result.stdout.strip() or result.stderr.strip()

    return {
        "status": (
            STATUS_HEALTHY
            if result.returncode == 0 and state == "active"
            else STATUS_CRITICAL
        ),
        "message": "service_state",
        "service": service_name,
        "state": state or "unknown",
    }


def get_uptime_seconds() -> float | None:
    proc_uptime = Path("/proc/uptime")

    if proc_uptime.is_file():
        try:
            return round(
                float(
                    proc_uptime.read_text(
                        encoding="utf-8"
                    ).split()[0]
                ),
                2,
            )
        except (OSError, ValueError, IndexError):
            return None

    try:
        return round(time.monotonic(), 2)
    except Exception:
        return None


def overall_status(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {
        item.get("status")
        for item in checks.values()
    }

    if STATUS_CRITICAL in statuses:
        return STATUS_CRITICAL

    if STATUS_WARNING in statuses:
        return STATUS_WARNING

    if STATUS_UNKNOWN in statuses:
        return STATUS_WARNING

    return STATUS_HEALTHY


def build_health_report(
    database_path: Path,
    backup_dir: Path,
    disk_path: Path,
    service_name: str = "alex-core.service",
    now: datetime | None = None,
) -> dict[str, Any]:

    current = now or utc_now()

    checks = {
        "database": check_database(database_path),
        "disk": check_disk(disk_path),
        "backup": check_backup(
            backup_dir=backup_dir,
            now=current,
        ),
        "core_service": check_service(service_name),
    }

    return {
        "schema_version": 1,
        "generated_at": current.astimezone(
            timezone.utc
        ).isoformat(),
        "status": overall_status(checks),
        "uptime_seconds": get_uptime_seconds(),
        "checks": checks,
    }


def write_report_atomic(
    output_path: Path,
    report: dict[str, Any],
) -> None:

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = output_path.with_name(
        output_path.name + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ALEX health monitor"
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
        "--disk-path",
        default="/var/lib/alex",
    )

    parser.add_argument(
        "--service",
        default="alex-core.service",
    )

    parser.add_argument(
        "--output",
        default="/var/lib/alex/health/health.json",
    )

    args = parser.parse_args()

    report = build_health_report(
        database_path=Path(args.database),
        backup_dir=Path(args.backup_dir),
        disk_path=Path(args.disk_path),
        service_name=args.service,
    )

    write_report_atomic(
        Path(args.output),
        report,
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
        ),
        flush=True,
    )

    return (
        1
        if report["status"] == STATUS_CRITICAL
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
