from pathlib import Path

import alex_watchdog


def test_healthy_resets_failure_counter(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "state.json"

    alex_watchdog.write_state(
        state,
        {
            "consecutive_failures": 2,
        },
    )

    monkeypatch.setattr(
        alex_watchdog,
        "health_endpoint_ok",
        lambda *args, **kwargs: (
            True,
            "ok",
        ),
    )

    result = (
        alex_watchdog.watchdog_iteration(
            state_path=state,
            health_url="http://test/health",
            service_name="alex-core.service",
        )
    )

    assert (
        result["consecutive_failures"]
        == 0
    )

    assert result["action"] == "none"


def test_first_failure_does_not_restart(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "state.json"

    monkeypatch.setattr(
        alex_watchdog,
        "health_endpoint_ok",
        lambda *args, **kwargs: (
            False,
            "timeout",
        ),
    )

    restarted = []

    monkeypatch.setattr(
        alex_watchdog,
        "force_recover_service",
        lambda service: (
            restarted.append(service)
        ),
    )

    result = (
        alex_watchdog.watchdog_iteration(
            state_path=state,
            health_url="http://test",
            service_name="alex-core.service",
            threshold=3,
            now_monotonic=100,
        )
    )

    assert (
        result["consecutive_failures"]
        == 1
    )

    assert restarted == []


def test_threshold_restarts_active_service(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "state.json"

    alex_watchdog.write_state(
        state,
        {
            "consecutive_failures": 2,
        },
    )

    monkeypatch.setattr(
        alex_watchdog,
        "health_endpoint_ok",
        lambda *args, **kwargs: (
            False,
            "timeout",
        ),
    )

    monkeypatch.setattr(
        alex_watchdog,
        "service_is_active",
        lambda service: True,
    )

    restarted = []

    monkeypatch.setattr(
        alex_watchdog,
        "force_recover_service",
        lambda service: (
            restarted.append(service)
        ),
    )

    result = (
        alex_watchdog.watchdog_iteration(
            state_path=state,
            health_url="http://test",
            service_name="alex-core.service",
            threshold=3,
            cooldown_seconds=120,
            now_monotonic=500,
        )
    )

    assert restarted == [
        "alex-core.service"
    ]

    assert (
        result["action"]
        == "forced_recovery"
    )

    assert (
        result["consecutive_failures"]
        == 0
    )

    assert (
        result["last_restart_monotonic"]
        == 500
    )


def test_cooldown_blocks_restart(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "state.json"

    alex_watchdog.write_state(
        state,
        {
            "consecutive_failures": 2,
            "last_restart_monotonic": 450,
        },
    )

    monkeypatch.setattr(
        alex_watchdog,
        "health_endpoint_ok",
        lambda *args, **kwargs: (
            False,
            "timeout",
        ),
    )

    restarted = []

    monkeypatch.setattr(
        alex_watchdog,
        "force_recover_service",
        lambda service: (
            restarted.append(service)
        ),
    )

    result = (
        alex_watchdog.watchdog_iteration(
            state_path=state,
            health_url="http://test",
            service_name="alex-core.service",
            threshold=3,
            cooldown_seconds=120,
            now_monotonic=500,
        )
    )

    assert restarted == []
    assert result["action"] == "cooldown"


def test_inactive_service_is_not_double_restarted(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "state.json"

    alex_watchdog.write_state(
        state,
        {
            "consecutive_failures": 2,
        },
    )

    monkeypatch.setattr(
        alex_watchdog,
        "health_endpoint_ok",
        lambda *args, **kwargs: (
            False,
            "timeout",
        ),
    )

    monkeypatch.setattr(
        alex_watchdog,
        "service_is_active",
        lambda service: False,
    )

    result = (
        alex_watchdog.watchdog_iteration(
            state_path=state,
            health_url="http://test",
            service_name="alex-core.service",
            threshold=3,
            now_monotonic=1000,
        )
    )

    assert (
        result["action"]
        == "service_not_active"
    )
