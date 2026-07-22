from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_UNITS = (
    "alex-core.service",
    "alex-health.timer",
    "alex-backup.timer",
    "alex-update.timer",
    "alex-watchdog.timer",
)


def unit_active(name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    return (
        result.returncode == 0
        and result.stdout.strip() == "active"
    )


def database_integrity(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "database_not_found"

    connection = None

    try:
        connection = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=5,
        )

        result = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()

        if result is None:
            return False, "no_result"

        return (
            result[0] == "ok",
            str(result[0]),
        )

    except sqlite3.Error as exc:
        return False, str(exc)

    finally:
        if connection is not None:
            connection.close()


def check_health_report(
    path: Path,
) -> tuple[bool, str]:

    if not path.is_file():
        return False, "health_report_missing"

    try:
        report = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        return False, f"invalid_health:{exc}"

    status = str(
        report.get(
            "status",
            "unknown",
        )
    )

    if status != "healthy":
        return False, status

    return True, status


def run_acceptance(
    database: Path,
    health_report: Path,
) -> dict[str, Any]:

    units = {
        name: unit_active(name)
        for name in REQUIRED_UNITS
    }

    db_ok, db_detail = database_integrity(
        database
    )

    health_ok, health_detail = (
        check_health_report(
            health_report
        )
    )

    passed = (
        all(units.values())
        and db_ok
        and health_ok
    )

    return {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "passed": passed,
        "database": {
            "ok": db_ok,
            "detail": db_detail,
        },
        "health": {
            "ok": health_ok,
            "detail": health_detail,
        },
        "units": units,
    }


def write_atomic(
    path: Path,
    report: dict[str, Any],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_name(
        path.name + ".tmp"
    )

    temp.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--database",
        default="/var/lib/alex/alex.db",
    )

    parser.add_argument(
        "--health",
        default=(
            "/var/lib/alex/health/"
            "health.json"
        ),
    )

    parser.add_argument(
        "--output",
        default=(
            "/var/lib/alex/boot/"
            "last-boot-check.json"
        ),
    )

    args = parser.parse_args()

    report = run_acceptance(
        Path(args.database),
        Path(args.health),
    )

    write_atomic(
        Path(args.output),
        report,
    )

    print(
        "BOOT_ACCEPTANCE "
        + json.dumps(report),
        flush=True,
    )

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
