from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SERVICE = (
    ROOT
    / "deploy"
    / "alex-boot-acceptance.service"
)


def test_boot_acceptance_wiring():
    text = SERVICE.read_text(
        encoding="ascii"
    )

    assert "Type=oneshot" in text
    assert "User=root" in text
    assert "ExecStartPre=/bin/sleep 20" in text
    assert "alex_boot_acceptance.py" in text

    for unit in (
        "alex-core.service",
        "alex-health.service",
    ):
        assert unit in text
