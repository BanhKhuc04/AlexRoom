import pytest
import os
from unittest.mock import patch

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

@pytest.fixture(autouse=True)
def mock_fail_closed(request):
    file_path = str(request.node.path).lower()
    needs_mock = any(marker in file_path for marker in ["c4", "c5", "c6", "c7", "c8"])
    
    if needs_mock:
        with patch("app.build_fail_closed_brain_request", lambda req: req):
            yield
    else:
        yield
