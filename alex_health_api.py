from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HEALTHY = "healthy"
WARNING = "warning"
CRITICAL = "critical"
UNKNOWN = "unknown"


def parse_timestamp(
    value: str | None,
) -> datetime | None:

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def unavailable_payload(
    message: str,
    path: Path,
) -> dict[str, Any]:

    return {
        "available": False,
        "stale": True,
        "status": UNKNOWN,
        "message": message,
        "generated_at": None,
        "file_age_seconds": None,
        "source": str(path),
        "report": None,
    }


def read_health_snapshot(
    path: Path,
    now: datetime | None = None,
    stale_after_seconds: float = 660.0,
) -> dict[str, Any]:
    """
    Read the report produced by alex-health.service.

    This function deliberately never creates a health report.
    alex_health.py remains the single monitoring authority.
    """

    path = path.expanduser().resolve()

    if not path.is_file():
        return unavailable_payload(
            "health_report_not_found",
            path,
        )

    try:
        document = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return unavailable_payload(
            "health_report_invalid",
            path,
        )

    if not isinstance(document, dict):
        return unavailable_payload(
            "health_report_invalid_payload",
            path,
        )

    generated_raw = document.get(
        "generated_at"
    )

    generated = parse_timestamp(
        str(generated_raw)
        if generated_raw is not None
        else None
    )

    current = now or datetime.now(
        timezone.utc
    )

    if current.tzinfo is None:
        current = current.replace(
            tzinfo=timezone.utc
        )

    if generated is not None:
        age_seconds = max(
            0.0,
            (
                current.astimezone(
                    timezone.utc
                )
                - generated
            ).total_seconds(),
        )
    else:
        try:
            modified = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            )

            age_seconds = max(
                0.0,
                (
                    current.astimezone(
                        timezone.utc
                    )
                    - modified
                ).total_seconds(),
            )
        except OSError:
            age_seconds = None

    stale = (
        age_seconds is None
        or age_seconds
        > stale_after_seconds
    )

    reported_status = str(
        document.get(
            "status",
            UNKNOWN,
        )
    ).lower()

    if reported_status not in {
        HEALTHY,
        WARNING,
        CRITICAL,
        UNKNOWN,
    }:
        reported_status = UNKNOWN

    # A previously healthy report must not stay "healthy"
    # forever if alex-health.timer stops running.
    effective_status = (
        WARNING
        if stale
        and reported_status == HEALTHY
        else reported_status
    )

    return {
        "available": True,
        "stale": stale,
        "status": effective_status,
        "reported_status": reported_status,
        "message": (
            "health_report_stale"
            if stale
            else "health_report_current"
        ),
        "generated_at": generated_raw,
        "file_age_seconds": (
            round(
                age_seconds,
                2,
            )
            if age_seconds is not None
            else None
        ),
        "source": str(path),
        "report": document,
    }
