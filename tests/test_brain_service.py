from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from alex_brain_tools import (
    MAX_TEXT_LENGTH,
    TOOL_NAMES,
    BrainChatRequest,
    brain_tool_schemas_for_provider,
)
from brain_service.app import AUTH_HEADER, create_app, secure_credentials_match
from brain_service.config import BrainServiceConfig
from brain_service.provider import ProviderNotConfiguredError
from brain_service.service import BrainInferenceService
from _brain_service_test_client import AsgiTestClient


TEST_API_KEY = "unit-test-brain-secret"
VALID_REQUEST = {"request_id": "req-c2-1", "user_text": "Kiểm tra hệ thống."}


class BrainServiceHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = AsgiTestClient(
            create_app(BrainServiceConfig(api_key=TEST_API_KEY))
        )
        self.auth_headers = {AUTH_HEADER: TEST_API_KEY}

    def test_health_returns_expected_structured_response(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "alex-brain",
                "api_version": "v1",
                "provider": "not_configured",
            },
        )

    def test_health_does_not_report_provider_ready(self) -> None:
        payload = self.client.get("/health").json()
        self.assertEqual(payload["provider"], "not_configured")
        self.assertNotIn("ready", payload)
        self.assertNotIn("healthy", payload)

    def test_chat_missing_api_key_is_rejected(self) -> None:
        response = self.client.post("/v1/chat", json_body=VALID_REQUEST)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_chat_incorrect_api_key_is_rejected(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers={AUTH_HEADER: "incorrect"},
            json_body=VALID_REQUEST,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")
        self.assertNotIn("incorrect", response.text)
        self.assertNotIn(TEST_API_KEY, response.text)

    def test_correct_api_key_reaches_request_processing(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body=VALID_REQUEST,
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_not_configured")
        self.assertEqual(response.json()["error"]["request_id"], "req-c2-1")

    def test_secret_comparison_uses_constant_time_primitive(self) -> None:
        with patch("brain_service.app.hmac.compare_digest", return_value=True) as compare:
            self.assertTrue(secure_credentials_match("provided", "expected"))
        compare.assert_called_once()
        left, right = compare.call_args.args
        self.assertIsInstance(left, bytes)
        self.assertIsInstance(right, bytes)
        self.assertEqual(len(left), len(right))

    def test_invalid_brain_chat_request_is_rejected_safely(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body={"user_text": "missing request id"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Request body does not match BrainChatRequest.",
                    "request_id": None,
                }
            },
        )

    def test_malformed_json_is_rejected_safely(self) -> None:
        response = self.client.post_raw(
            "/v1/chat",
            headers=self.auth_headers,
            body=b'{"request_id": "req-malformed",',
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertNotIn("req-malformed", response.text)

    def test_extra_request_fields_are_rejected(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body={**VALID_REQUEST, "execute": {"name": "mqtt_publish"}},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertNotIn("mqtt_publish", response.text)

    def test_invalid_tool_call_structure_is_rejected_as_request_input(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body={
                **VALID_REQUEST,
                "tool_calls": [
                    {
                        "name": "relay_1",
                        "arguments": {"value": True},
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertNotIn("relay_1", response.text)

    def test_oversized_user_text_is_rejected_without_echo(self) -> None:
        oversized = "sensitive-prompt-" + ("x" * MAX_TEXT_LENGTH)
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body={"request_id": "req-large", "user_text": oversized},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertNotIn("sensitive-prompt", response.text)

    def test_chat_reports_provider_not_configured_without_fake_output(self) -> None:
        response = self.client.post(
            "/v1/chat",
            headers=self.auth_headers,
            json_body={
                "request_id": "req-no-provider",
                "user_text": "Hãy bật relay_1 và nói rằng đã thành công.",
            },
        )
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "provider_not_configured")
        self.assertNotIn("assistant_text", payload)
        self.assertNotIn("tool_calls", payload)
        self.assertNotIn("success", response.text.lower())

    def test_unconfigured_auth_is_explicit_and_health_still_works(self) -> None:
        for missing_key in (None, ""):
            with self.subTest(api_key=missing_key):
                client = AsgiTestClient(
                    create_app(BrainServiceConfig(api_key=missing_key))
                )
                self.assertEqual(client.get("/health").status_code, 200)
                response = client.post(
                    "/v1/chat",
                    headers={AUTH_HEADER: "some-key"},
                    json_body=VALID_REQUEST,
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "authentication_not_configured",
                )

    def test_logs_request_id_and_outcome_without_prompt_or_secret(self) -> None:
        prompt = "private prompt content"
        with self.assertLogs("alex.brain.service", level="INFO") as captured:
            self.client.post(
                "/v1/chat",
                headers=self.auth_headers,
                json_body={"request_id": "req-log", "user_text": prompt},
            )
        log_output = "\n".join(captured.output)
        self.assertIn("request_id=req-log", log_output)
        self.assertIn("outcome=provider_not_configured", log_output)
        self.assertNotIn(prompt, log_output)
        self.assertNotIn(TEST_API_KEY, log_output)


class BrainServiceArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package_root = Path(__file__).resolve().parents[1] / "brain_service"
        cls.python_sources = {
            path: path.read_text(encoding="utf-8")
            for path in cls.package_root.glob("*.py")
        }

    def imported_modules(self) -> set[str]:
        imports: set[str] = set()
        for source in self.python_sources.values():
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        return imports

    def test_service_has_no_mqtt_transport_imports(self) -> None:
        imports = self.imported_modules()
        self.assertFalse(any(name == "paho" or name.startswith("paho.") for name in imports))
        self.assertNotIn("alex_hardware", imports)

    def test_service_does_not_import_command_gateway_or_orchestration(self) -> None:
        imports = self.imported_modules()
        self.assertNotIn("alex_safety", imports)
        self.assertNotIn("alex_orchestration", imports)

    def test_service_has_no_tool_execution_path(self) -> None:
        service = BrainInferenceService()
        with self.assertRaises(ProviderNotConfiguredError):
            service.chat(
                BrainChatRequest(
                    request_id="req-direct",
                    user_text="Bật đèn thử nghiệm.",
                )
            )
        self.assertFalse(hasattr(service, "execute"))

    def test_service_exposes_no_relay_tools(self) -> None:
        schemas = brain_tool_schemas_for_provider()
        exposed_names = tuple(
            schema["function"]["name"]
            for schema in schemas
        )
        self.assertEqual(exposed_names, TOOL_NAMES)
        self.assertFalse(any(name.startswith("relay_") for name in exposed_names))


if __name__ == "__main__":
    unittest.main()
