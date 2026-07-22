from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy" / "alex-health.service"
TIMER = ROOT / "deploy" / "alex-health.timer"


def test_health_service_wiring():
    text = SERVICE.read_text(encoding="ascii")

    assert "[Service]" in text
    assert "Type=oneshot" in text
    assert "User=vanhkhuc" in text

    assert (
        "WorkingDirectory="
        "/opt/alex/AlexRoom-0.2.0-hardware-rc"
    ) in text

    assert "UMask=0077" in text

    assert (
        "ExecStart="
        "/opt/alex/AlexRoom-0.2.0-hardware-rc/.venv/bin/python "
        "/opt/alex/AlexRoom-0.2.0-hardware-rc/alex_health.py "
        "--database /var/lib/alex/alex.db "
        "--backup-dir /var/lib/alex/backups "
        "--disk-path /var/lib/alex "
        "--service alex-core.service "
        "--output /var/lib/alex/health/health.json"
    ) in text


def test_health_timer_wiring():
    text = TIMER.read_text(encoding="ascii")

    assert "[Timer]" in text
    assert "OnBootSec=2m" in text
    assert "OnUnitActiveSec=5m" in text
    assert "AccuracySec=30s" in text
    assert "Persistent=true" in text
    assert "Unit=alex-health.service" in text
    assert "WantedBy=timers.target" in text
