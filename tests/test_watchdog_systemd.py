from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SERVICE = (
    ROOT / "deploy"
    / "alex-watchdog.service"
)

TIMER = (
    ROOT / "deploy"
    / "alex-watchdog.timer"
)


def test_watchdog_service():
    text = SERVICE.read_text(
        encoding="ascii"
    )

    assert "Type=oneshot" in text

    assert (
        "alex_watchdog.py"
        in text
    )

    assert (
        "--threshold 3"
        in text
    )

    assert (
        "--cooldown 120"
        in text
    )

    assert (
        "--timeout 3"
        in text
    )


def test_watchdog_timer():
    text = TIMER.read_text(
        encoding="ascii"
    )

    assert "OnBootSec=3m" in text
    assert "OnUnitActiveSec=1m" in text
    assert "Persistent=true" in text
