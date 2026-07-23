from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from alex_brain_tools import (
    MAX_TOOL_CALLS,
    TOOL_NAMES,
    BrainChatRequest,
    brain_tool_schemas_for_provider,
)
from brain_service.app import AUTH_HEADER, create_app
from brain_service.config import BrainServiceConfig
from brain_service.provider import (
    SYSTEM_INSTRUCTION,
    InvalidProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from brain_service.providers import build_provider
from brain_service.providers.ollama_native import (
    OLLAMA_NUM_PREDICT,
    OllamaNativeProvider,
)
from brain_service.service import BrainInferenceService
from _brain_service_test_client import AsgiTestClient


TEST_BRAIN_KEY = "ollama-brain-client-secret"


class FakeTransport:
    def __init__(
        self,
        response: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = (
            {"message": {"content": "", "tool_calls": []}}
            if response is None
            else response
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    def post_json(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeUrlopenResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeUrlopenResponse":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, _: int) -> bytes:
        return self.body


def native_response(
    name: object,
    arguments: object,
    *,
    content: object = "",
    call_id: str = "call-provider-metadata",
    index: int = 0,
) -> dict[str, object]:
    return {
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call_id,
                    "provider_metadata": {"ignored": True},
                    "function": {
                        "index": index,
                        "name": name,
                        "arguments": arguments,
                    },
                }
            ],
        }
    }


class OllamaNativeProviderTests(unittest.TestCase):
    def provider(
        self,
        transport: FakeTransport,
        *,
        base_url: str = "http://127.0.0.1:11434",
    ) -> OllamaNativeProvider:
        return OllamaNativeProvider(
            base_url=base_url,
            model="qwen3.5:4b",
            api_key=None,
            timeout_seconds=30,
            transport=transport,
        )

    def service_response(
        self,
        upstream: dict[str, object],
        *,
        prompt: str = "Kiểm tra ALEX.",
    ):
        service = BrainInferenceService(
            self.provider(FakeTransport(response=upstream))
        )
        return service.chat(
            BrainChatRequest(
                request_id="req-ollama",
                user_text=prompt,
            )
        )

    def assert_invalid(self, upstream: dict[str, object]) -> None:
        with self.assertRaises(InvalidProviderResponseError):
            self.service_response(upstream)

    def test_provider_selection_ollama_native_works(self) -> None:
        provider = build_provider(
            BrainServiceConfig(
                api_key=TEST_BRAIN_KEY,
                provider="ollama_native",
                provider_url="http://127.0.0.1:11434",
                provider_model="qwen3.5:4b",
            )
        )
        self.assertIsInstance(provider, OllamaNativeProvider)
        self.assertTrue(provider.configured)

    def test_base_url_becomes_owned_native_chat_endpoint(self) -> None:
        self.assertEqual(
            self.provider(FakeTransport()).url,
            "http://127.0.0.1:11434/api/chat",
        )

    def test_trailing_slash_is_normalized_safely(self) -> None:
        self.assertEqual(
            self.provider(
                FakeTransport(),
                base_url="http://127.0.0.1:11434/",
            ).url,
            "http://127.0.0.1:11434/api/chat",
        )
        self.assertEqual(
            self.provider(
                FakeTransport(),
                base_url="http://127.0.0.1:11434/api/chat/",
            ).url,
            "http://127.0.0.1:11434/api/chat",
        )

    def test_native_request_has_deterministic_generation_settings(self) -> None:
        transport = FakeTransport()
        self.provider(transport).infer(
            system_instruction=SYSTEM_INSTRUCTION,
            user_text="Bật đèn test.",
            tools=brain_tool_schemas_for_provider(),
        )
        payload = transport.calls[0]["payload"]
        self.assertIs(payload["think"], False)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(
            payload["options"]["num_predict"],
            OLLAMA_NUM_PREDICT,
        )

    def test_vietnamese_request_is_encoded_as_explicit_utf8(self) -> None:
        upstream = json.dumps(
            {"message": {"content": "Được.", "tool_calls": []}},
            ensure_ascii=False,
        ).encode("utf-8")
        fake_response = FakeUrlopenResponse(upstream)
        provider = OllamaNativeProvider(
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
            api_key=None,
            timeout_seconds=30,
        )
        with patch(
            "brain_service.providers.openai_compatible.urllib.request.urlopen",
            return_value=fake_response,
        ) as urlopen:
            provider.infer(
                system_instruction=SYSTEM_INSTRUCTION,
                user_text="Bật đèn thử nghiệm.",
                tools=brain_tool_schemas_for_provider(),
            )
        request = urlopen.call_args.args[0]
        self.assertIn("Bật đèn thử nghiệm.".encode("utf-8"), request.data)
        self.assertNotIn(b"\\u1ead", request.data)

    def test_native_request_uses_exact_c1_registry_tool_schemas(self) -> None:
        transport = FakeTransport()
        self.provider(transport).infer(
            system_instruction=SYSTEM_INSTRUCTION,
            user_text="status",
            tools=brain_tool_schemas_for_provider(),
        )
        schemas = transport.calls[0]["payload"]["tools"]
        names = tuple(schema["function"]["name"] for schema in schemas)
        self.assertEqual(names, TOOL_NAMES)
        self.assertEqual(
            set(schemas[2]["function"]["parameters"]["properties"]),
            {"value"},
        )

    def test_valid_native_tool_proposals_parse_through_c1(self) -> None:
        valid = (
            ("system_status", {}),
            ("list_devices", {}),
            ("set_test_led", {"value": True}),
            ("set_room_mode", {"mode": "study"}),
            ("run_safe_mission", {"mission_id": "safe-mission"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-automation"},
            ),
        )
        for name, arguments in valid:
            with self.subTest(name=name):
                response = self.service_response(
                    native_response(name, arguments)
                )
                self.assertEqual(response.tool_calls[0].name, name)
                self.assertEqual(
                    response.tool_calls[0].arguments,
                    arguments,
                )

    def test_provider_id_index_and_metadata_are_ignored(self) -> None:
        response = self.service_response(
            native_response(
                "set_test_led",
                {"value": True},
                call_id="call-secret-provider-id",
                index=73,
            )
        )
        call = response.tool_calls[0]
        self.assertEqual(call.arguments, {"value": True})
        serialized = call.model_dump()
        self.assertNotIn("id", serialized)
        self.assertNotIn("index", serialized)
        self.assertNotIn("provider_metadata", serialized)

    def test_provider_id_cannot_become_tool_argument(self) -> None:
        response = self.service_response(
            native_response(
                "system_status",
                {},
                call_id="must-not-enter-arguments",
            )
        )
        self.assertEqual(response.tool_calls[0].arguments, {})

    def test_empty_content_with_valid_tool_call_is_accepted(self) -> None:
        response = self.service_response(
            native_response("set_test_led", {"value": True}, content="")
        )
        self.assertEqual(response.assistant_text, "")
        self.assertEqual(response.tool_calls[0].arguments, {"value": True})

    def test_forbidden_native_tool_names_are_rejected(self) -> None:
        for name in ("mqtt_publish", "set_relay", "relay_1"):
            with self.subTest(name=name):
                self.assert_invalid(native_response(name, {}))

    def test_set_test_led_extra_target_fields_are_rejected(self) -> None:
        extras = (
            ("node_id", "esp01"),
            ("capability", "relay_1"),
            ("target", "relay_1"),
            ("relay", "relay_1"),
            ("topic", "alex/device/esp01/command"),
        )
        for field, value in extras:
            with self.subTest(field=field):
                self.assert_invalid(
                    native_response(
                        "set_test_led",
                        {"value": True, field: value},
                    )
                )

    def test_malformed_or_non_object_arguments_are_rejected(self) -> None:
        for arguments in (
            None,
            [],
            "{}",
            True,
            1,
            {"value": object()},
        ):
            with self.subTest(arguments=arguments):
                self.assert_invalid(
                    native_response("set_test_led", arguments)
                )

    def test_mixed_valid_invalid_response_rejects_entire_response(self) -> None:
        upstream = {
            "message": {
                "content": "mixed",
                "tool_calls": [
                    native_response("system_status", {})["message"]["tool_calls"][0],
                    native_response("mqtt_publish", {})["message"]["tool_calls"][0],
                ],
            }
        }
        self.assert_invalid(upstream)

    def test_more_than_four_calls_are_rejected(self) -> None:
        call = native_response("system_status", {})["message"]["tool_calls"][0]
        upstream = {
            "message": {
                "content": "",
                "tool_calls": [call] * (MAX_TOOL_CALLS + 1),
            }
        }
        self.assert_invalid(upstream)

    def test_malformed_native_response_is_rejected(self) -> None:
        malformed = (
            {},
            {"message": "bad"},
            {"message": {"content": []}},
            {"message": {"content": "", "tool_calls": {}}},
            {"message": {"content": "", "tool_calls": ["bad"]}},
            {"message": {"content": "", "tool_calls": [{}]}},
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"function": "bad"}],
                }
            },
        )
        for upstream in malformed:
            with self.subTest(upstream=upstream):
                self.assert_invalid(upstream)


class OllamaNativeErrorAndArchitectureTests(unittest.TestCase):
    def client_with_transport_error(self, error: Exception) -> AsgiTestClient:
        provider = OllamaNativeProvider(
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
            api_key=None,
            timeout_seconds=30,
            transport=FakeTransport(error=error),
        )
        return AsgiTestClient(
            create_app(
                BrainServiceConfig(api_key=TEST_BRAIN_KEY),
                BrainInferenceService(provider),
            )
        )

    def post(self, client: AsgiTestClient):
        return client.post(
            "/v1/chat",
            headers={AUTH_HEADER: TEST_BRAIN_KEY},
            json_body={
                "request_id": "req-ollama-error",
                "user_text": "Kiểm tra hệ thống.",
            },
        )

    def test_timeout_maps_to_provider_timeout(self) -> None:
        response = self.post(
            self.client_with_transport_error(
                ProviderTimeoutError("raw timeout detail")
            )
        )
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "provider_timeout")
        self.assertNotIn("raw timeout detail", response.text)

    def test_connection_failure_maps_to_provider_unavailable(self) -> None:
        response = self.post(
            self.client_with_transport_error(
                ProviderUnavailableError("connection detail")
            )
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"],
            "provider_unavailable",
        )
        self.assertNotIn("connection detail", response.text)

    def test_raw_ollama_response_body_is_not_leaked(self) -> None:
        secret = "raw Ollama body with filesystem path and secret"
        response = self.post(
            self.client_with_transport_error(
                ProviderUnavailableError(secret)
            )
        )
        self.assertNotIn(secret, response.text)

    def test_ollama_provider_introduces_no_execution_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1] / "brain_service"
        imports: set[str] = set()
        function_names: set[str] = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_names.add(node.name)
        forbidden = {
            "paho",
            "alex_hardware",
            "alex_safety",
            "alex_orchestration",
            "RPi.GPIO",
            "gpiozero",
        }
        self.assertTrue(imports.isdisjoint(forbidden))
        self.assertNotIn("execute", function_names)
        self.assertNotIn("publish", function_names)


if __name__ == "__main__":
    unittest.main()
