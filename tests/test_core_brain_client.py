from __future__ import annotations

import json
import socket
import unittest
from urllib.error import URLError

from alex_brain_client import (
    BRAIN_AUTH_HEADER,
    MAX_BRAIN_RESPONSE_BYTES,
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
    build_brain_chat_url,
)
from alex_brain_tools import BrainChatRequest


VALID_REQUEST = BrainChatRequest(
    request_id="req-c4-client",
    user_text="Trạng thái hệ thống?",
)


def brain_response(
    *,
    request_id: str = "req-c4-client",
    assistant_text: str = "Tôi sẽ đọc trạng thái từ Core.",
    tool_calls: list[dict[str, object]] | None = None,
) -> bytes:
    return json.dumps(
        {
            "request_id": request_id,
            "assistant_text": assistant_text,
            "tool_calls": tool_calls or [],
        }
    ).encode("utf-8")


class FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.read_amount: int | None = None

    def read(self, amount: int = -1) -> bytes:
        self.read_amount = amount
        return self.body

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class RecordingOpener:
    def __init__(
        self,
        body: bytes = brain_response(),
        error: Exception | None = None,
    ) -> None:
        self.response = FakeHttpResponse(body)
        self.error = error
        self.requests: list[object] = []
        self.timeouts: list[float] = []

    def __call__(self, request, *, timeout: float):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return self.response


class CoreBrainConfigTests(unittest.TestCase):
    def test_disabled_is_fail_safe_default(self) -> None:
        config = CoreBrainConfig.from_env({})
        self.assertFalse(config.enabled)
        self.assertFalse(config.configured)

    def test_only_explicit_true_values_enable_brain(self) -> None:
        for raw in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(
                    CoreBrainConfig.from_env(
                        {"ALEX_BRAIN_ENABLED": raw}
                    ).enabled
                )
        for raw in ("", "0", "false", "enabled", "invalid"):
            with self.subTest(raw=raw):
                self.assertFalse(
                    CoreBrainConfig.from_env(
                        {"ALEX_BRAIN_ENABLED": raw}
                    ).enabled
                )

    def test_timeout_is_bounded(self) -> None:
        self.assertEqual(
            CoreBrainConfig.from_env(
                {"ALEX_BRAIN_TIMEOUT_SECONDS": "-5"}
            ).timeout_seconds,
            0.1,
        )
        self.assertEqual(
            CoreBrainConfig.from_env(
                {"ALEX_BRAIN_TIMEOUT_SECONDS": "500"}
            ).timeout_seconds,
            30.0,
        )
        self.assertEqual(
            CoreBrainConfig.from_env(
                {"ALEX_BRAIN_TIMEOUT_SECONDS": "not-a-number"}
            ).timeout_seconds,
            5.0,
        )

    def test_chat_url_is_fixed_and_safe(self) -> None:
        self.assertEqual(
            build_brain_chat_url("http://127.0.0.1:8765/"),
            "http://127.0.0.1:8765/v1/chat",
        )
        self.assertEqual(
            build_brain_chat_url("https://brain.local/base"),
            "https://brain.local/base/v1/chat",
        )
        for unsafe in (
            "",
            "ftp://brain.local",
            "http://user:secret@brain.local",
            "http://brain.local/?redirect=bad",
            "http://brain.local/#fragment",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaisesRegex(
                    BrainClientError,
                    "brain_not_configured",
                ):
                    build_brain_chat_url(unsafe)


class CoreBrainClientTests(unittest.TestCase):
    def configured_client(
        self,
        opener: RecordingOpener,
        *,
        client_key: str = "brain-client-secret",
    ) -> CoreBrainClient:
        return CoreBrainClient(
            CoreBrainConfig(
                enabled=True,
                url="http://127.0.0.1:8765",
                client_key=client_key,
                timeout_seconds=2.5,
            ),
            opener=opener,
        )

    def assert_error(
        self,
        expected: str,
        client: CoreBrainClient,
    ) -> None:
        with self.assertRaises(BrainClientError) as raised:
            client.chat(VALID_REQUEST)
        self.assertEqual(raised.exception.code, expected)

    def test_constructing_disabled_client_performs_no_network_call(self) -> None:
        opener = RecordingOpener()
        client = CoreBrainClient(CoreBrainConfig(), opener=opener)
        self.assertEqual(opener.requests, [])
        self.assert_error("brain_disabled", client)
        self.assertEqual(opener.requests, [])

    def test_missing_url_or_key_is_not_configured(self) -> None:
        for config in (
            CoreBrainConfig(enabled=True, client_key="key"),
            CoreBrainConfig(enabled=True, url="http://brain.local"),
        ):
            with self.subTest(config=config):
                opener = RecordingOpener()
                self.assert_error(
                    "brain_not_configured",
                    CoreBrainClient(config, opener=opener),
                )
                self.assertEqual(opener.requests, [])

    def test_sends_valid_contract_auth_header_and_bounded_timeout(self) -> None:
        opener = RecordingOpener(
            brain_response(
                tool_calls=[{"name": "system_status", "arguments": {}}]
            )
        )
        response = self.configured_client(opener).chat(VALID_REQUEST)

        self.assertEqual(response.tool_calls[0].name, "system_status")
        self.assertEqual(len(opener.requests), 1)
        outbound = opener.requests[0]
        self.assertEqual(outbound.full_url, "http://127.0.0.1:8765/v1/chat")
        headers = {
            name.lower(): value
            for name, value in outbound.header_items()
        }
        self.assertEqual(
            headers[BRAIN_AUTH_HEADER.lower()],
            "brain-client-secret",
        )
        self.assertEqual(outbound.get_method(), "POST")
        self.assertEqual(opener.timeouts, [2.5])
        self.assertEqual(
            json.loads(outbound.data),
            VALID_REQUEST.model_dump(mode="json"),
        )
        self.assertEqual(
            opener.response.read_amount,
            MAX_BRAIN_RESPONSE_BYTES + 1,
        )

    def test_brain_secret_is_not_returned_in_parsed_response(self) -> None:
        secret = "never-return-this-brain-secret"
        response = self.configured_client(
            RecordingOpener(),
            client_key=secret,
        ).chat(VALID_REQUEST)
        self.assertNotIn(secret, response.model_dump_json())

    def test_timeout_maps_to_bounded_error(self) -> None:
        self.assert_error(
            "brain_timeout",
            self.configured_client(
                RecordingOpener(error=socket.timeout("raw timeout details"))
            ),
        )

    def test_connection_failure_maps_to_bounded_error(self) -> None:
        self.assert_error(
            "brain_unavailable",
            self.configured_client(
                RecordingOpener(
                    error=URLError("connection refused with raw details")
                )
            ),
        )

    def test_malformed_json_is_rejected(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(RecordingOpener(b"{not-json")),
        )

    def test_malformed_contract_is_rejected(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(
                RecordingOpener(
                    json.dumps(
                        {
                            "request_id": "req-c4-client",
                            "assistant_text": "bad",
                            "tool_calls": "not-a-list",
                        }
                    ).encode()
                )
            ),
        )

    def test_unknown_tool_is_rejected_structurally(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(
                RecordingOpener(
                    brain_response(
                        tool_calls=[
                            {"name": "mqtt_publish", "arguments": {}}
                        ]
                    )
                )
            ),
        )

    def test_relay_proposal_is_rejected_structurally(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(
                RecordingOpener(
                    brain_response(
                        tool_calls=[
                            {
                                "name": "relay_1",
                                "arguments": {"value": True},
                            }
                        ]
                    )
                )
            ),
        )

    def test_request_id_mismatch_is_invalid(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(
                RecordingOpener(
                    brain_response(request_id="different-request")
                )
            ),
        )

    def test_oversized_response_is_invalid(self) -> None:
        self.assert_error(
            "invalid_brain_response",
            self.configured_client(
                RecordingOpener(b"x" * (MAX_BRAIN_RESPONSE_BYTES + 1))
            ),
        )


if __name__ == "__main__":
    unittest.main()
