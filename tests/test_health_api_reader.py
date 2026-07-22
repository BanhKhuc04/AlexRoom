import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alex_health_api import (
    CRITICAL,
    HEALTHY,
    UNKNOWN,
    WARNING,
    read_health_snapshot,
)


def test_missing_report_is_unknown():
    with tempfile.TemporaryDirectory() as directory:
        path = (
            Path(directory)
            / "health.json"
        )

        result = read_health_snapshot(
            path
        )

        assert result["available"] is False
        assert result["stale"] is True
        assert result["status"] == UNKNOWN
        assert result["report"] is None


def test_fresh_health_report():
    with tempfile.TemporaryDirectory() as directory:
        path = (
            Path(directory)
            / "health.json"
        )

        now = datetime(
            2026,
            7,
            22,
            12,
            0,
            tzinfo=timezone.utc,
        )

        path.write_text(
            json.dumps(
                {
                    "schema_version": 4,
                    "generated_at": (
                        now
                        - timedelta(
                            seconds=30
                        )
                    ).isoformat(),
                    "status": HEALTHY,
                    "checks": {},
                }
            ),
            encoding="utf-8",
        )

        result = read_health_snapshot(
            path,
            now=now,
        )

        assert result["available"] is True
        assert result["stale"] is False
        assert result["status"] == HEALTHY
        assert (
            result["file_age_seconds"]
            == 30.0
        )


def test_stale_healthy_report_becomes_warning():
    with tempfile.TemporaryDirectory() as directory:
        path = (
            Path(directory)
            / "health.json"
        )

        now = datetime(
            2026,
            7,
            22,
            12,
            0,
            tzinfo=timezone.utc,
        )

        path.write_text(
            json.dumps(
                {
                    "schema_version": 4,
                    "generated_at": (
                        now
                        - timedelta(
                            minutes=20
                        )
                    ).isoformat(),
                    "status": HEALTHY,
                    "checks": {},
                }
            ),
            encoding="utf-8",
        )

        result = read_health_snapshot(
            path,
            now=now,
        )

        assert result["stale"] is True
        assert result["status"] == WARNING
        assert (
            result["reported_status"]
            == HEALTHY
        )


def test_critical_report_stays_critical():
    with tempfile.TemporaryDirectory() as directory:
        path = (
            Path(directory)
            / "health.json"
        )

        now = datetime.now(
            timezone.utc
        )

        path.write_text(
            json.dumps(
                {
                    "schema_version": 4,
                    "generated_at": (
                        now.isoformat()
                    ),
                    "status": CRITICAL,
                    "checks": {},
                }
            ),
            encoding="utf-8",
        )

        result = read_health_snapshot(
            path,
            now=now,
        )

        assert (
            result["status"]
            == CRITICAL
        )


def test_invalid_json_never_crashes_api_reader():
    with tempfile.TemporaryDirectory() as directory:
        path = (
            Path(directory)
            / "health.json"
        )

        path.write_text(
            "{broken",
            encoding="utf-8",
        )

        result = read_health_snapshot(
            path
        )

        assert result["available"] is False
        assert result["status"] == UNKNOWN
        assert (
            result["message"]
            == "health_report_invalid"
        )
