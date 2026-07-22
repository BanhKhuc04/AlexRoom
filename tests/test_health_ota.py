import alex_health

from alex_health import (
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_UNKNOWN,
    check_timer,
    check_update_state,
)


def test_update_timer_healthy(
    monkeypatch,
):
    values = {
        "ActiveState": "active",
        "SubState": "waiting",
        "NextElapseUSecRealtime": (
            "Wed 2026-07-22 12:00:00 UTC"
        ),
        "LastTriggerUSec": (
            "Wed 2026-07-22 11:55:00 UTC"
        ),
    }

    monkeypatch.setattr(
        alex_health,
        "systemctl_property",
        lambda unit, prop: values.get(prop),
    )

    result = check_timer(
        "alex-update.timer"
    )

    assert (
        result["status"]
        == STATUS_HEALTHY
    )

    assert (
        result["active_state"]
        == "active"
    )

    assert (
        result["sub_state"]
        == "waiting"
    )


def test_update_timer_inactive_is_critical(
    monkeypatch,
):
    values = {
        "ActiveState": "inactive",
        "SubState": "dead",
    }

    monkeypatch.setattr(
        alex_health,
        "systemctl_property",
        lambda unit, prop: values.get(prop),
    )

    result = check_timer(
        "alex-update.timer"
    )

    assert (
        result["status"]
        == STATUS_CRITICAL
    )


def test_timer_unknown_when_systemd_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        alex_health,
        "systemctl_property",
        lambda unit, prop: None,
    )

    result = check_timer(
        "alex-update.timer"
    )

    assert (
        result["status"]
        == STATUS_UNKNOWN
    )


def test_last_update_success(
    monkeypatch,
):
    values = {
        "Result": "success",
        "ExecMainStatus": "0",
        "ActiveState": "inactive",
        "SubState": "dead",
        "ExecMainExitTimestamp": (
            "Wed 2026-07-22 11:55:01 UTC"
        ),
        "StateChangeTimestamp": (
            "Wed 2026-07-22 11:55:01 UTC"
        ),
    }

    monkeypatch.setattr(
        alex_health,
        "systemctl_property",
        lambda unit, prop: values.get(prop),
    )

    result = check_update_state()

    assert (
        result["status"]
        == STATUS_HEALTHY
    )

    assert (
        result["message"]
        == "last_update_success"
    )

    assert result["exec_status"] == 0


def test_last_update_failure_is_critical(
    monkeypatch,
):
    values = {
        "Result": "exit-code",
        "ExecMainStatus": "1",
        "ActiveState": "failed",
        "SubState": "failed",
    }

    monkeypatch.setattr(
        alex_health,
        "systemctl_property",
        lambda unit, prop: values.get(prop),
    )

    result = check_update_state()

    assert (
        result["status"]
        == STATUS_CRITICAL
    )

    assert (
        result["message"]
        == "last_update_failed"
    )

    assert result["exec_status"] == 1
