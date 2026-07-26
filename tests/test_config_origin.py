import json
import subprocess
from unittest.mock import patch

import pytest

import app
from app import normalize_canonical_origin


def test_normalize_canonical_origin_valid_https():
    assert normalize_canonical_origin("https://orangepione.tail81f539.ts.net") == "https://orangepione.tail81f539.ts.net"
    assert normalize_canonical_origin("https://localhost:8000") == "https://localhost:8000"
    assert normalize_canonical_origin("https://my-domain.com/") == "https://my-domain.com"
    assert normalize_canonical_origin("  https://test.com  ") == "https://test.com"


def test_normalize_canonical_origin_invalid():
    # Non-HTTPS
    assert normalize_canonical_origin("http://orangepione.tail81f539.ts.net") == ""
    assert normalize_canonical_origin("javascript:alert(1)") == ""
    assert normalize_canonical_origin("ws://test.com") == ""
    # Credentials
    assert normalize_canonical_origin("https://user:pass@test.com") == ""
    # Paths, query, fragment
    assert normalize_canonical_origin("https://test.com/path") == ""
    assert normalize_canonical_origin("https://test.com/?query=1") == ""
    assert normalize_canonical_origin("https://test.com/#fragment") == ""
    # Empty
    assert normalize_canonical_origin("") == ""
    assert normalize_canonical_origin("   ") == ""




def test_resolve_canonical_origin_env_override():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {"ALEX_CANONICAL_ORIGIN": "https://env.ts.net"}), patch("subprocess.run") as mock_run:
            assert app.resolve_canonical_origin() == "https://env.ts.net"
            mock_run.assert_not_called()


def test_resolve_canonical_origin_tailscale_fallback():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps({"Self": {"DNSName": "orangepione.tail81f539.ts.net."}})
            assert app.resolve_canonical_origin() == "https://orangepione.tail81f539.ts.net"
            mock_run.assert_called_once_with(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True
            )


def test_resolve_canonical_origin_tailscale_invalid_json():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "invalid json"
            assert app.resolve_canonical_origin() == ""


def test_resolve_canonical_origin_tailscale_timeout():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tailscale", timeout=3)):
            assert app.resolve_canonical_origin() == ""


@pytest.mark.parametrize("json_output", [
    "{}",
    '{"Self": null}',
    '{"Self": []}',
    '{"Self": "foo"}',
    '{"Self": {}}',
    '{"Self": {"DNSName": null}}',
    '{"Self": {"DNSName": 123}}',
    '{"Self": {"DNSName": ""}}',
    '{"Self": {"DNSName": "   "}}',
])
def test_resolve_canonical_origin_tailscale_malformed_json(json_output):
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = json_output
        assert app.resolve_canonical_origin() == ""


def test_resolve_canonical_origin_tailscale_called_process_error():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tailscale")):
        assert app.resolve_canonical_origin() == ""


def test_resolve_canonical_origin_caches_result():
    app._cached_canonical_origin = None
    with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = json.dumps({"Self": {"DNSName": "cache.ts.net."}})
        assert app.resolve_canonical_origin() == "https://cache.ts.net"
        mock_run.assert_called_once()
        assert app.resolve_canonical_origin() == "https://cache.ts.net"
        mock_run.assert_called_once()
