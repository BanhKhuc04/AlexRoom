import json
from datetime import datetime, timedelta, timezone

import alex_health

from alex_health import (
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_WARNING,
    check_hardware_runtime,
    parse_iso_datetime,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    def read(self):
        return json.dumps(
            self.payload
        ).encode("utf-8")


def install_response(
    monkeypatch,
    payload,
):
    monkeypatch.setattr(
        alex_health.urllib.request,
        "urlopen",
        lambda request, timeout=5: (
            FakeResponse(payload)
        ),
    )


def test_parse_iso_datetime():
    value = parse_iso_datetime(
        "2026-07-22T12:00:00+00:00"
    )

    assert value is not None
    assert value.tzinfo is not None


def test_hardware_runtime_healthy(
    monkeypatch,
):
    now = datetime(
        2026,
        7,
        22,
        12,
        0,
        30,
        tzinfo=timezone.utc,
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "connected",
            "device": "online",
            "last_seen": (
                now
                - timedelta(seconds=10)
            ).isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now
    )

    assert result["status"] == (
        STATUS_HEALTHY
    )

    assert result["mqtt"] == (
        "connected"
    )

    assert result["device"] == (
        "online"
    )

    assert (
        result["heartbeat_age_seconds"]
        == 10.0
    )


def test_mqtt_disconnected_is_critical(
    monkeypatch,
):
    now = datetime.now(
        timezone.utc
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "disconnected",
            "device": "degraded",
            "last_seen": now.isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now
    )

    assert result["status"] == (
        STATUS_CRITICAL
    )

    assert result["message"] == (
        "mqtt_disconnected"
    )


def test_device_offline_is_critical(
    monkeypatch,
):
    now = datetime.now(
        timezone.utc
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "connected",
            "device": "offline",
            "last_seen": (
                now
                - timedelta(seconds=100)
            ).isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now
    )

    assert result["status"] == (
        STATUS_CRITICAL
    )

    assert result["message"] == (
        "device_offline"
    )


def test_degraded_device_is_warning(
    monkeypatch,
):
    now = datetime.now(
        timezone.utc
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "connected",
            "device": "degraded",
            "last_seen": now.isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now
    )

    assert result["status"] == (
        STATUS_WARNING
    )


def test_delayed_heartbeat_is_warning(
    monkeypatch,
):
    now = datetime.now(
        timezone.utc
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "connected",
            "device": "online",
            "last_seen": (
                now
                - timedelta(seconds=60)
            ).isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now,
    )

    assert result["status"] == (
        STATUS_WARNING
    )

    assert result["message"] == (
        "heartbeat_delayed"
    )


def test_stale_heartbeat_is_critical(
    monkeypatch,
):
    now = datetime.now(
        timezone.utc
    )

    install_response(
        monkeypatch,
        {
            "api": "online",
            "mqtt": "connected",
            "device": "online",
            "last_seen": (
                now
                - timedelta(seconds=120)
            ).isoformat(),
        },
    )

    result = check_hardware_runtime(
        now=now,
    )

    assert result["status"] == (
        STATUS_CRITICAL
    )

    assert result["message"] == (
        "heartbeat_stale"
    )


def test_invalid_response_is_critical(
    monkeypatch,
):
    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc,
            traceback,
        ):
            return False

        def read(self):
            return b"not-json"

    monkeypatch.setattr(
        alex_health.urllib.request,
        "urlopen",
        lambda request, timeout=5: (
            BadResponse()
        ),
    )

    result = check_hardware_runtime()

    assert result["status"] == (
        STATUS_CRITICAL
    )

    assert result["message"] == (
        "core_health_invalid_response"
    )
