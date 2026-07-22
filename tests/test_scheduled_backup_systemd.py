from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy" / "alex-backup.service"
TIMER = ROOT / "deploy" / "alex-backup.timer"


def test_backup_service_wiring():
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
        "/opt/alex/AlexRoom-0.2.0-hardware-rc/alex_scheduled_backup.py "
        "--database /var/lib/alex/alex.db "
        "--backup-dir /var/lib/alex/backups "
        "--keep 14"
    ) in text


def test_backup_timer_wiring():
    text = TIMER.read_text(encoding="ascii")

    assert "[Timer]" in text
    assert "OnCalendar=*-*-* 03:15:00 Asia/Ho_Chi_Minh" in text
    assert "Persistent=true" in text
    assert "RandomizedDelaySec=5m" in text
    assert "Unit=alex-backup.service" in text
    assert "WantedBy=timers.target" in text

