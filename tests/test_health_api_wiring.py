from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def test_system_health_api_is_wired():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert (
        "from alex_health_api "
        "import read_health_snapshot"
    ) in text

    assert (
        "ALEX_HEALTH_REPORT_PATH"
        in text
    )

    assert (
        '@app.get("/api/system/health")'
        in text
    )

    assert (
        "read_health_snapshot("
        in text
    )


def test_existing_connectivity_health_remains():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert '@app.get("/health")' in text
