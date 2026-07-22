from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOURNALD = ROOT / "deploy" / "alex-journald.conf"
LOGROTATE = ROOT / "deploy" / "alex-logrotate"


def test_journald_retention_policy():
    text = JOURNALD.read_text(encoding="ascii")

    assert "[Journal]" in text
    assert "Storage=persistent" in text
    assert "Compress=yes" in text
    assert "SystemMaxUse=200M" in text
    assert "SystemKeepFree=500M" in text
    assert "SystemMaxFileSize=25M" in text
    assert "MaxRetentionSec=14day" in text
    assert "MaxFileSec=1day" in text


def test_file_log_rotation_policy():
    text = LOGROTATE.read_text(encoding="ascii")

    assert "/var/log/alex/*.log" in text
    assert "daily" in text
    assert "rotate 14" in text
    assert "maxsize 20M" in text
    assert "compress" in text
    assert "missingok" in text
    assert "copytruncate" in text
