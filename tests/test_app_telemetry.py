import sys
import json
import logging
from unittest.mock import Mock, patch

from alex_intelligence_router import IntelligenceRouteObservation
import os
os.environ["ALEX_API_KEY"] = "dummy"
os.environ["MQTT_PASSWORD"] = "dummy"

# Using importlib to reload app in order to test handler logic if necessary,
# but we can also just import the functions.
from app import _get_telemetry_logger, _route_observation_sink

def test_telemetry_logger_configuration() -> None:
    logger = _get_telemetry_logger()

    assert logger.name == "alex.intelligence.telemetry"
    assert logger.level == logging.INFO
    assert logger.propagate is False

    stderr_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr]
    assert len(stderr_handlers) == 1

def test_no_duplicate_handler_behavior() -> None:
    logger = _get_telemetry_logger()
    original_stderr_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr]
    assert len(original_stderr_handlers) == 1

    # Call it again to simulate repeated setup
    logger_again = _get_telemetry_logger()
    assert logger_again is logger
    new_stderr_handlers = [h for h in logger_again.handlers if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr]
    assert len(new_stderr_handlers) == 1
    assert new_stderr_handlers == original_stderr_handlers

def test_route_observation_sink_emits_structured_json(capsys) -> None:
    obs = IntelligenceRouteObservation(
        request_id="test-req-123",
        route_outcome="execute_action",
        route_reason="deterministic_safe_action",
        brain_called=False,
        deterministic=True,
        restricted=False,
        selected_tool="set_test_led",
        started_at="2026-07-25T00:00:00Z",
        duration_ms=42,
        brain_duration_ms=None,
        execution_duration_ms=10,
        success=True,
        error_code=None,
    )

    logger = _get_telemetry_logger()
    import io
    string_stream = io.StringIO()
    # Find the correct handler to replace its stream
    stderr_handler = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr)

    # Replace the handler's stream for the duration of the test
    old_stream = stderr_handler.stream
    stderr_handler.stream = string_stream

    try:
        _route_observation_sink(obs)

        output = string_stream.getvalue()

        # A. Runtime telemetry visibility
        # E. No sensitive fields
        assert output.startswith("Intelligence route observation ")
        assert "test-req-123" in output
        assert "execute_action" in output
        assert "duration_ms" in output
        assert "success" in output
        assert "error_code" in output

        assert "user_text" not in output
        assert "credentials" not in output
        assert "api_key" not in output

        # Verify it is valid JSON
        json_payload = output[len("Intelligence route observation "):].strip()
        data = json.loads(json_payload)
        assert data["request_id"] == "test-req-123"
        assert data["route_outcome"] == "execute_action"
        assert data["duration_ms"] == 42
        assert data["success"] is True
    finally:
        logger.handlers[0].stream = old_stream
