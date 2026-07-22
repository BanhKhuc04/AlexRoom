from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alex_restore import RestoreService
from alex_store import AlexStore


def run_systemctl(
    action: str,
    service: str,
) -> None:
    result = subprocess.run(
        [
            "systemctl",
            action,
            service,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit={result.returncode}"
        )

        raise RuntimeError(
            f"systemctl {action} {service} failed: "
            f"{detail}"
        )


def service_active(
    service: str,
) -> bool:
    result = subprocess.run(
        [
            "systemctl",
            "is-active",
            service,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    return (
        result.returncode == 0
        and result.stdout.strip() == "active"
    )


def wait_service_state(
    service: str,
    expected_active: bool,
    *,
    timeout: float = 20.0,
    checker: Callable[[str], bool] = service_active,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if checker(service) is expected_active:
            return

        time.sleep(0.25)

    expected = (
        "active"
        if expected_active
        else "inactive"
    )

    raise RuntimeError(
        f"{service} did not become {expected}"
    )


def read_health(
    url: str,
) -> dict:
    try:
        with urllib.request.urlopen(
            url,
            timeout=5,
        ) as response:
            return json.load(response)

    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(
            f"Health request failed: {exc}"
        ) from exc


def health_is_ready(
    health: dict,
) -> bool:
    return (
        health.get("api") == "online"
        and health.get("mqtt") == "connected"
        and health.get("device") == "online"
    )


def wait_health(
    url: str,
    *,
    timeout: float = 90.0,
    reader: Callable[[str], dict] = read_health,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None

    while time.monotonic() < deadline:
        try:
            last = reader(url)

            if health_is_ready(last):
                return last

        except RuntimeError:
            pass

        time.sleep(1)

    raise RuntimeError(
        "ALEX production health did not recover: "
        f"{last}"
    )


def production_restore(
    *,
    filename: str,
    confirmation: str,
    database: Path,
    backup_dir: Path,
    rollback_dir: Path,
    service_name: str = "alex-core",
    health_url: str = (
        "http://127.0.0.1:8000/health"
    ),
    systemctl: Callable[
        [str, str],
        None,
    ] = run_systemctl,
    state_checker: Callable[
        [str],
        bool,
    ] = service_active,
    health_waiter: Callable[
        [str],
        dict,
    ] = wait_health,
) -> dict:
    if confirmation != "RESTORE-PRODUCTION":
        raise PermissionError(
            "Confirmation must be RESTORE-PRODUCTION"
        )

    store = AlexStore(database)

    restore_service = RestoreService(
        store,
        backup_dir,
        rollback_dir,
    )

    # Validate before touching the running service.
    validated = restore_service.validate(
        filename
    )

    service_was_active = state_checker(
        service_name
    )

    if not service_was_active:
        raise RuntimeError(
            f"{service_name} must be active "
            "before production restore"
        )

    rollback_file: str | None = None

    try:
        systemctl(
            "stop",
            service_name,
        )

        wait_service_state(
            service_name,
            False,
            checker=state_checker,
        )

        result = restore_service.restore(
            filename,
            confirmation="RESTORE",
            service_stopped=True,
        )

        rollback_file = result[
            "rollback_file"
        ]

        systemctl(
            "start",
            service_name,
        )

        wait_service_state(
            service_name,
            True,
            checker=state_checker,
        )

        health = health_waiter(
            health_url
        )

        return {
            "restored": True,
            "file": filename,
            "sha256": validated[
                "actual_sha256"
            ],
            "rollback_file": rollback_file,
            "health": health,
            "automatic_rollback": False,
        }

    except Exception as restore_error:
        rollback_error = None
        rollback_health = None

        try:
            if state_checker(
                service_name
            ):
                systemctl(
                    "stop",
                    service_name,
                )

                wait_service_state(
                    service_name,
                    False,
                    checker=state_checker,
                )

            if rollback_file is not None:
                restore_service.restore_rollback(
                    rollback_file,
                    confirmation="ROLLBACK",
                    service_stopped=True,
                )

            systemctl(
                "start",
                service_name,
            )

            wait_service_state(
                service_name,
                True,
                checker=state_checker,
            )

            rollback_health = (
                health_waiter(
                    health_url
                )
            )

        except Exception as exc:
            rollback_error = exc

        if rollback_error is not None:
            raise RuntimeError(
                "Production restore failed and "
                "automatic rollback also failed: "
                f"restore={restore_error}; "
                f"rollback={rollback_error}"
            ) from rollback_error

        raise RuntimeError(
            "Production restore failed; "
            "automatic rollback completed; "
            f"health={rollback_health}; "
            f"cause={restore_error}"
        ) from restore_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded ALEX production database restore "
            "with automatic service recovery."
        )
    )

    parser.add_argument(
        "filename",
    )

    parser.add_argument(
        "--confirm",
        required=True,
    )

    parser.add_argument(
        "--database",
        default=os.getenv(
            "ALEX_DATABASE_PATH"
        ),
    )

    parser.add_argument(
        "--backup-dir",
        default=os.getenv(
            "ALEX_BACKUP_DIR"
        ),
    )

    parser.add_argument(
        "--rollback-dir",
        default=os.getenv(
            "ALEX_RESTORE_ROLLBACK_DIR"
        ),
    )

    parser.add_argument(
        "--service",
        default="alex-core",
    )

    parser.add_argument(
        "--health-url",
        default=(
            "http://127.0.0.1:8000/health"
        ),
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.database:
        print(
            "ERROR: ALEX_DATABASE_PATH "
            "or --database is required",
            file=sys.stderr,
        )
        return 1

    database = Path(
        args.database
    )

    backup_dir = Path(
        args.backup_dir
        or database.parent / "backups"
    )

    rollback_dir = Path(
        args.rollback_dir
        or database.parent / "restore-rollback"
    )

    try:
        result = production_restore(
            filename=args.filename,
            confirmation=args.confirm,
            database=database,
            backup_dir=backup_dir,
            rollback_dir=rollback_dir,
            service_name=args.service,
            health_url=args.health_url,
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
