from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
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
            "backup_count": 0,
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
            "backup_count": 0,
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
        "backup_count": len(backups),
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


def systemctl_property(
    service_name: str,
    property_name: str,
) -> str | None:
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                f"--property={property_name}",
                "--value",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()

    return value or None


def check_core_runtime(
    service_name: str,
) -> dict[str, Any]:

    restart_raw = systemctl_property(
        service_name,
        "NRestarts",
    )

    pid_raw = systemctl_property(
        service_name,
        "MainPID",
    )

    try:
        restart_count = (
            int(restart_raw)
            if restart_raw is not None
            else None
        )
    except ValueError:
        restart_count = None

    try:
        main_pid = (
            int(pid_raw)
            if pid_raw is not None
            else None
        )
    except ValueError:
        main_pid = None

    if restart_count is None:
        status = STATUS_UNKNOWN
    elif restart_count >= 5:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "core_runtime",
        "service": service_name,
        "restart_count": restart_count,
        "main_pid": main_pid,
    }


def parse_meminfo(
    path: Path = Path("/proc/meminfo"),
) -> dict[str, int] | None:

    if not path.is_file():
        return None

    values: dict[str, int] = {}

    try:
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines():

            if ":" not in line:
                continue

            name, raw = line.split(
                ":",
                1,
            )

            parts = raw.strip().split()

            if not parts:
                continue

            value = int(parts[0])

            # /proc/meminfo values are normally kB.
            values[name] = value * 1024

    except (OSError, ValueError):
        return None

    return values


def check_memory(
    meminfo_path: Path = Path("/proc/meminfo"),
    warning_percent: float = 85.0,
    critical_percent: float = 95.0,
) -> dict[str, Any]:

    info = parse_meminfo(
        meminfo_path
    )

    if not info:
        return {
            "status": STATUS_UNKNOWN,
            "message": "memory_unavailable",
        }

    total = info.get("MemTotal")
    available = info.get("MemAvailable")

    if not total or available is None:
        return {
            "status": STATUS_UNKNOWN,
            "message": "memory_values_missing",
        }

    used = max(
        0,
        total - available,
    )

    used_percent = (
        used / total * 100.0
    )

    if used_percent >= critical_percent:
        status = STATUS_CRITICAL
    elif used_percent >= warning_percent:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "memory_usage",
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": round(
            used_percent,
            2,
        ),
    }


def check_cpu_temperature() -> dict[str, Any]:
    candidates = [
        Path(
            "/sys/class/thermal/"
            "thermal_zone0/temp"
        ),
        Path(
            "/sys/class/hwmon/"
            "hwmon0/temp1_input"
        ),
    ]

    temperature = None
    source = None

    for path in candidates:
        if not path.is_file():
            continue

        try:
            raw = float(
                path.read_text(
                    encoding="utf-8"
                ).strip()
            )
        except (OSError, ValueError):
            continue

        # Linux thermal values are usually millidegrees.
        temperature = (
            raw / 1000.0
            if raw > 1000
            else raw
        )

        source = str(path)
        break

    if temperature is None:
        return {
            "status": STATUS_UNKNOWN,
            "message": "cpu_temperature_unavailable",
        }

    if temperature >= 85:
        status = STATUS_CRITICAL
    elif temperature >= 75:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "cpu_temperature",
        "celsius": round(
            temperature,
            1,
        ),
        "source": source,
    }


def check_load_average() -> dict[str, Any]:
    if not hasattr(os, "getloadavg"):
        return {
            "status": STATUS_UNKNOWN,
            "message": "load_average_unavailable",
        }

    try:
        load_1m, load_5m, load_15m = (
            os.getloadavg()
        )
    except OSError:
        return {
            "status": STATUS_UNKNOWN,
            "message": "load_average_unavailable",
        }

    cpu_count = os.cpu_count() or 1
    load_per_cpu = load_5m / cpu_count

    if load_per_cpu >= 2.0:
        status = STATUS_CRITICAL
    elif load_per_cpu >= 1.0:
        status = STATUS_WARNING
    else:
        status = STATUS_HEALTHY

    return {
        "status": status,
        "message": "load_average",
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "cpu_count": cpu_count,
        "load_5m_per_cpu": round(
            load_per_cpu,
            2,
        ),
    }


def check_timer(
    timer_name: str,
) -> dict[str, Any]:

    active_state = systemctl_property(
        timer_name,
        "ActiveState",
    )

    sub_state = systemctl_property(
        timer_name,
        "SubState",
    )

    next_trigger = systemctl_property(
        timer_name,
        "NextElapseUSecRealtime",
    )

    last_trigger = systemctl_property(
        timer_name,
        "LastTriggerUSec",
    )

    if active_state is None:
        return {
            "status": STATUS_UNKNOWN,
            "message": "timer_state_unavailable",
            "timer": timer_name,
        }

    if (
        active_state == "active"
        and sub_state in {
            "waiting",
            "running",
            "elapsed",
        }
    ):
        status = STATUS_HEALTHY
    else:
        status = STATUS_CRITICAL

    return {
        "status": status,
        "message": "timer_state",
        "timer": timer_name,
        "active_state": active_state,
        "sub_state": sub_state,
        "next_trigger": next_trigger,
        "last_trigger": last_trigger,
    }


def check_update_state(
    service_name: str = "alex-update.service",
) -> dict[str, Any]:

    result = systemctl_property(
        service_name,
        "Result",
    )

    exec_status_raw = systemctl_property(
        service_name,
        "ExecMainStatus",
    )

    active_state = systemctl_property(
        service_name,
        "ActiveState",
    )

    sub_state = systemctl_property(
        service_name,
        "SubState",
    )

    exit_timestamp = systemctl_property(
        service_name,
        "ExecMainExitTimestamp",
    )

    state_timestamp = systemctl_property(
        service_name,
        "StateChangeTimestamp",
    )

    try:
        exec_status = (
            int(exec_status_raw)
            if exec_status_raw is not None
            else None
        )
    except ValueError:
        exec_status = None

    if (
        result is None
        and exec_status is None
        and active_state is None
    ):
        status = STATUS_UNKNOWN
        message = "update_state_unavailable"

    elif (
        result in {
            "failed",
            "exit-code",
            "signal",
            "core-dump",
            "timeout",
            "watchdog",
            "resources",
        }
        or (
            exec_status is not None
            and exec_status != 0
        )
    ):
        status = STATUS_CRITICAL
        message = "last_update_failed"

    else:
        status = STATUS_HEALTHY

        if active_state == "active":
            message = "update_running"
        elif result == "success":
            message = "last_update_success"
        else:
            message = "update_idle"

    return {
        "status": status,
        "message": message,
        "service": service_name,
        "result": result,
        "exec_status": exec_status,
        "active_state": active_state,
        "sub_state": sub_state,
        "last_exit": exit_timestamp,
        "state_changed": state_timestamp,
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
        except (
            OSError,
            ValueError,
            IndexError,
        ):
            return None

    try:
        return round(
            time.monotonic(),
            2,
        )
    except Exception:
        return None


def get_boot_time(
    now: datetime | None = None,
) -> str | None:

    uptime = get_uptime_seconds()

    if uptime is None:
        return None

    current = now or utc_now()

    boot_time = (
        current.astimezone(timezone.utc)
        - timedelta(seconds=uptime)
    )

    return boot_time.isoformat()


def get_alex_version() -> str | None:
    try:
        from alex_version import ALEX_VERSION
        return str(ALEX_VERSION)
    except Exception:
        return None


def overall_status(
    checks: dict[str, dict[str, Any]],
) -> str:

    statuses = {
        item.get("status")
        for item in checks.values()
    }

    if STATUS_CRITICAL in statuses:
        return STATUS_CRITICAL

    if STATUS_WARNING in statuses:
        return STATUS_WARNING

    # Optional metrics being unavailable must not mark
    # the whole appliance unhealthy.
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
        "database": check_database(
            database_path
        ),
        "disk": check_disk(
            disk_path
        ),
        "memory": check_memory(),
        "cpu_temperature": (
            check_cpu_temperature()
        ),
        "load_average": (
            check_load_average()
        ),
        "backup": check_backup(
            backup_dir=backup_dir,
            now=current,
        ),
        "core_service": check_service(
            service_name
        ),
        "core_runtime": check_core_runtime(
            service_name
        ),
        "update_timer": check_timer(
            "alex-update.timer"
        ),
        "update": check_update_state(
            "alex-update.service"
        ),
    }

    uptime = get_uptime_seconds()

    return {
        "schema_version": 3,
        "generated_at": (
            current
            .astimezone(timezone.utc)
            .isoformat()
        ),
        "status": overall_status(
            checks
        ),
        "alex_version": (
            get_alex_version()
        ),
        "uptime_seconds": uptime,
        "boot_time": (
            get_boot_time(current)
        ),
        "checks": checks,
    }


def write_report_atomic(
    output_path: Path,
    report: dict[str, Any],
) -> None:

    output_path = (
        output_path
        .expanduser()
        .resolve()
    )

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

    temporary.replace(
        output_path
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "ALEX health monitor V2"
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
        "--disk-path",
        default="/var/lib/alex",
    )

    parser.add_argument(
        "--service",
        default="alex-core.service",
    )

    parser.add_argument(
        "--output",
        default=(
            "/var/lib/alex/health/"
            "health.json"
        ),
    )

    args = parser.parse_args()

    report = build_health_report(
        database_path=Path(
            args.database
        ),
        backup_dir=Path(
            args.backup_dir
        ),
        disk_path=Path(
            args.disk_path
        ),
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
        if report["status"]
        == STATUS_CRITICAL
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
