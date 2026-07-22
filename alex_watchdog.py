from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 120.0


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "consecutive_failures": 0,
            "last_restart_monotonic": None,
            "last_result": "unknown",
        }

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return {
            "consecutive_failures": 0,
            "last_restart_monotonic": None,
            "last_result": "invalid_state_reset",
        }

    if not isinstance(data, dict):
        return {
            "consecutive_failures": 0,
            "last_restart_monotonic": None,
            "last_result": "invalid_state_reset",
        }

    return data


def write_state(
    path: Path,
    state: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def health_endpoint_ok(
    url: str,
    timeout_seconds: float = 3.0,
) -> tuple[bool, str]:

    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "alex-watchdog",
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            raw = response.read()

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
    ) as exc:
        return False, f"request_failed:{exc}"

    try:
        payload = json.loads(
            raw.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return False, "invalid_json"

    if not isinstance(payload, dict):
        return False, "invalid_payload"

    if payload.get("api") != "online":
        return False, "api_not_online"

    return True, "ok"


def service_is_active(
    service_name: str,
) -> bool:

    result = subprocess.run(
        [
            "systemctl",
            "is-active",
            service_name,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    return (
        result.returncode == 0
        and result.stdout.strip() == "active"
    )


def force_recover_service(
    service_name: str,
) -> None:
    """Force-kill a hung service.

    alex-core.service owns the restart policy. The watchdog only
    forces the unhealthy process to exit; systemd then performs
    the bounded Restart=on-failure recovery.
    """

    result = subprocess.run(
        [
            "systemctl",
            "kill",
            "--kill-who=all",
            "--signal=SIGKILL",
            service_name,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "force_kill_failed:"
            + (
                result.stderr.strip()
                or result.stdout.strip()
                or str(result.returncode)
            )
        )


def watchdog_iteration(
    *,
    state_path: Path,
    health_url: str,
    service_name: str,
    threshold: int = DEFAULT_THRESHOLD,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    timeout_seconds: float = 3.0,
    now_monotonic: float | None = None,
) -> dict[str, Any]:

    if threshold < 1:
        raise ValueError(
            "threshold_must_be_positive"
        )

    now = (
        time.monotonic()
        if now_monotonic is None
        else now_monotonic
    )

    state = load_state(state_path)

    healthy, detail = health_endpoint_ok(
        health_url,
        timeout_seconds=timeout_seconds,
    )

    if healthy:
        state.update(
            {
                "consecutive_failures": 0,
                "last_result": "healthy",
                "detail": detail,
                "action": "none",
            }
        )

        write_state(
            state_path,
            state,
        )

        return state

    failures = int(
        state.get(
            "consecutive_failures",
            0,
        )
    ) + 1

    state["consecutive_failures"] = failures
    state["last_result"] = "unhealthy"
    state["detail"] = detail
    state["action"] = "none"

    last_restart = state.get(
        "last_restart_monotonic"
    )

    cooldown_active = (
        isinstance(
            last_restart,
            (int, float),
        )
        and (
            now - float(last_restart)
            < cooldown_seconds
        )
    )

    if (
        failures >= threshold
        and not cooldown_active
    ):
        # If systemd already considers the service dead,
        # Restart=on-failure remains the primary recovery layer.
        if service_is_active(service_name):
            force_recover_service(
                service_name
            )

            state[
                "last_restart_monotonic"
            ] = now

            state[
                "consecutive_failures"
            ] = 0

            state[
                "action"
            ] = "forced_recovery"

        else:
            state[
                "action"
            ] = "service_not_active"

    elif cooldown_active:
        state["action"] = "cooldown"

    write_state(
        state_path,
        state,
    )

    return state


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "ALEX local API watchdog"
        )
    )

    parser.add_argument(
        "--health-url",
        default=(
            "http://127.0.0.1:8000/health"
        ),
    )

    parser.add_argument(
        "--service",
        default="alex-core.service",
    )

    parser.add_argument(
        "--state",
        default=(
            "/var/lib/alex/watchdog/state.json"
        ),
    )

    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
    )

    parser.add_argument(
        "--cooldown",
        type=float,
        default=DEFAULT_COOLDOWN_SECONDS,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
    )

    args = parser.parse_args()

    try:
        result = watchdog_iteration(
            state_path=Path(args.state),
            health_url=args.health_url,
            service_name=args.service,
            threshold=args.threshold,
            cooldown_seconds=args.cooldown,
            timeout_seconds=args.timeout,
        )

    except Exception as exc:
        print(
            f"WATCHDOG_FAILED {exc}",
            flush=True,
        )
        return 1

    print(
        "WATCHDOG_OK "
        + json.dumps(
            result,
            ensure_ascii=False,
        ),
        flush=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
