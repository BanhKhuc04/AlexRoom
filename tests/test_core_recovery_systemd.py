from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RECOVERY = (
    ROOT
    / "deploy"
    / "systemd"
    / "alex-core-recovery.conf"
)


def test_core_recovery_policy():
    text = RECOVERY.read_text(
        encoding="ascii"
    )

    assert "[Unit]" in text
    assert "StartLimitIntervalSec=60" in text
    assert "StartLimitBurst=5" in text

    assert "[Service]" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=3s" in text


def test_core_recovery_does_not_use_restart_always():
    text = RECOVERY.read_text(
        encoding="ascii"
    )

    assert "Restart=always" not in text
