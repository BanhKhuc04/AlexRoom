import tempfile
from pathlib import Path

from alex_health import (
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_WARNING,
    check_memory,
    overall_status,
    parse_meminfo,
)


def test_parse_meminfo():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meminfo"

        path.write_text(
            "MemTotal:       1000000 kB\n"
            "MemAvailable:    750000 kB\n",
            encoding="utf-8",
        )

        result = parse_meminfo(
            path
        )

        assert result is not None
        assert (
            result["MemTotal"]
            == 1000000 * 1024
        )
        assert (
            result["MemAvailable"]
            == 750000 * 1024
        )


def test_memory_healthy():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meminfo"

        path.write_text(
            "MemTotal:       1000000 kB\n"
            "MemAvailable:    700000 kB\n",
            encoding="utf-8",
        )

        result = check_memory(
            path
        )

        assert (
            result["status"]
            == STATUS_HEALTHY
        )

        assert (
            result["used_percent"]
            == 30.0
        )


def test_memory_warning():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meminfo"

        path.write_text(
            "MemTotal:       1000000 kB\n"
            "MemAvailable:    100000 kB\n",
            encoding="utf-8",
        )

        result = check_memory(
            path
        )

        assert (
            result["status"]
            == STATUS_WARNING
        )


def test_memory_critical():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meminfo"

        path.write_text(
            "MemTotal:       1000000 kB\n"
            "MemAvailable:     40000 kB\n",
            encoding="utf-8",
        )

        result = check_memory(
            path
        )

        assert (
            result["status"]
            == STATUS_CRITICAL
        )


def test_unknown_optional_metric_does_not_fail_overall():
    checks = {
        "database": {
            "status": STATUS_HEALTHY,
        },
        "temperature": {
            "status": "unknown",
        },
    }

    assert (
        overall_status(checks)
        == STATUS_HEALTHY
    )
