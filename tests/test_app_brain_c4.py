from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_client import (  # noqa: E402
    BrainClientError,
    CoreBrainClient,
    CoreBrainConfig,
)
from alex_brain_integration import CoreBrainIntegration  # noqa: E402
from alex_brain_tools import BrainChatRequest, BrainChatResponse  # noqa: E402


CORE_AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}
VALID_BODY = {
    "request_id": "req-c4-endpoint",
    "user_text": "Trạng thái hệ thống ALEX hiện thế nào?",
}


def brain_response(
    name: str | None = None,
    arguments: dict[str, object] | None = None,
    *,
    assistant_text: str = "Brain chỉ đề xuất.",
) -> BrainChatResponse:
    calls = (
        []
        if name is None
        else [{"name": name, "arguments": arguments or {}}]
    )
    return BrainChatResponse.model_validate(
        {
            "request_id": VALID_BODY["request_id"],
            "assistant_text": assistant_text,
            "tool_calls": calls,
        }
    )


class StubClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[BrainChatRequest] = []

    def chat(self, request: BrainChatRequest):
        self.requests.append(request)
        return self.response


class StubEndpointService:
    def __init__(
        self,
        response: object | None = None,
        error: BrainClientError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[BrainChatRequest] = []

    def chat(self, request: BrainChatRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class CoreBrainEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = AsgiTestClient(alex_app.app)

    def post(
        self,
        body: dict[str, object] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        return self.client.post(
            "/api/v1/brain/chat",
            headers=headers,
            json_body=body or VALID_BODY,
        )

    def test_endpoint_requires_existing_core_authentication(self) -> None:
        response = self.post()
        self.assertEqual(response.status_code, 401)

    def test_brain_server_key_is_not_accepted_as_core_auth(self) -> None:
        response = self.post(
            headers={"X-ALEX-Brain-Key": "server-to-server-only"}
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_core_auth_reaches_brain_specific_service(self) -> None:
        service = StubEndpointService(
            response=alex_app.CoreBrainChatResponse(
                request_id=VALID_BODY["request_id"],
                assistant_text="No tools.",
            )
        )
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(headers=CORE_AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(
            service.requests[0].model_dump(mode="json"),
            VALID_BODY,
        )

    def test_disabled_brain_returns_bounded_specific_failure(self) -> None:
        service = StubEndpointService(
            error=BrainClientError("brain_disabled")
        )
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(headers=CORE_AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": {"code": "brain_disabled"}},
        )

    def test_missing_brain_configuration_maps_safely(self) -> None:
        service = StubEndpointService(
            error=BrainClientError("brain_not_configured")
        )
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(headers=CORE_AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["code"],
            "brain_not_configured",
        )

    def test_timeout_and_unavailable_have_bounded_status(self) -> None:
        for code, expected_status in (
            ("brain_timeout", 504),
            ("brain_unavailable", 503),
            ("invalid_brain_response", 502),
        ):
            with self.subTest(code=code):
                service = StubEndpointService(
                    error=BrainClientError(code)
                )
                with patch.object(
                    alex_app,
                    "core_brain_integration",
                    service,
                ):
                    response = self.post(headers=CORE_AUTH)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(
                    response.json(),
                    {"detail": {"code": code}},
                )

    def test_extra_request_field_is_rejected_before_service(self) -> None:
        service = StubEndpointService()
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(
                {**VALID_BODY, "node_id": "relay_1"},
                headers=CORE_AUTH,
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.requests, [])

    def test_oversized_user_text_is_rejected_before_service(self) -> None:
        service = StubEndpointService()
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(
                {
                    "request_id": VALID_BODY["request_id"],
                    "user_text": "x" * 4097,
                },
                headers=CORE_AUTH,
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.requests, [])

    def test_core_still_functions_when_brain_is_disabled(self) -> None:
        disabled = CoreBrainIntegration(
            CoreBrainClient(CoreBrainConfig(enabled=False)),
            system_status_reader=alex_app._authoritative_system_status,
            device_list_reader=alex_app._authoritative_device_list,
            audit=lambda stage, level, details: None,
        )
        with (
            patch.object(alex_app, "core_brain_integration", disabled),
            patch.object(
                alex_app.store,
                "health",
                return_value={"state": "online", "schema_version": 1},
            ),
        ):
            brain = self.post(headers=CORE_AUTH)
            info = alex_app.info()
            status = alex_app.v1_status()

        self.assertEqual(brain.status_code, 503)
        self.assertEqual(info["status"], "running")
        self.assertEqual(status["api_version"], "1")
        self.assertEqual(status["safety_policy"], "central_gateway")

    def test_system_status_result_is_from_existing_core_implementation(self) -> None:
        service = CoreBrainIntegration(
            StubClient(
                brain_response(
                    "system_status",
                    assistant_text="Model claims MQTT is connected.",
                )
            ),
            system_status_reader=alex_app._authoritative_system_status,
            device_list_reader=alex_app._authoritative_device_list,
            audit=lambda stage, level, details: None,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.object(
                alex_app.store,
                "health",
                return_value={"state": "core-database-truth"},
            ),
        ):
            response = self.post(headers=CORE_AUTH)

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            body["tool_results"][0]["result"]["database"]["state"],
            "core-database-truth",
        )
        self.assertEqual(
            body["assistant_text"],
            "Model claims MQTT is connected.",
        )

    def test_list_devices_result_is_from_existing_core_registry(self) -> None:
        service = CoreBrainIntegration(
            StubClient(brain_response("list_devices")),
            system_status_reader=alex_app._authoritative_system_status,
            device_list_reader=alex_app._authoritative_device_list,
            audit=lambda stage, level, details: None,
        )
        with patch.object(alex_app, "core_brain_integration", service):
            response = self.post(headers=CORE_AUTH)

        result = response.json()["tool_results"][0]["result"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["node_id"], "esp01")
        self.assertIn("capabilities", result["items"][0])

    def test_mutation_proposals_cannot_reach_any_hardware_or_executor(self) -> None:
        cases = (
            ("set_test_led", {"value": True}),
            ("set_room_mode", {"mode": "sleep"}),
            ("run_safe_mission", {"mission_id": "safe-study"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-check"},
            ),
        )
        original_mode = alex_app.device_state["mode"]
        for name, arguments in cases:
            with self.subTest(name=name):
                service = CoreBrainIntegration(
                    StubClient(brain_response(name, arguments)),
                    system_status_reader=alex_app._authoritative_system_status,
                    device_list_reader=alex_app._authoritative_device_list,
                    audit=lambda stage, level, details: None,
                )
                with (
                    patch.object(
                        alex_app,
                        "core_brain_integration",
                        service,
                    ),
                    patch.object(
                        alex_app.command_gateway,
                        "request",
                    ) as gateway,
                    patch.object(
                        alex_app.mqtt_client,
                        "publish",
                    ) as mqtt_publish,
                    patch.object(
                        alex_app.mission_executor,
                        "run",
                    ) as mission,
                    patch.object(
                        alex_app.automation_executor,
                        "evaluate",
                    ) as automation,
                ):
                    response = self.post(headers=CORE_AUTH)

                self.assertEqual(response.status_code, 200)
                result = response.json()["tool_results"][0]
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(
                    result["reason"],
                    "tool_not_enabled_in_c4",
                )
                gateway.assert_not_called()
                mqtt_publish.assert_not_called()
                mission.assert_not_called()
                automation.assert_not_called()
                self.assertEqual(
                    alex_app.device_state["mode"],
                    original_mode,
                )

    def test_mixed_batch_cannot_reach_gateway_mqtt_or_core_read(self) -> None:
        mixed = BrainChatResponse.model_validate(
            {
                "request_id": VALID_BODY["request_id"],
                "assistant_text": "Mixed",
                "tool_calls": [
                    {"name": "system_status", "arguments": {}},
                    {
                        "name": "set_test_led",
                        "arguments": {"value": True},
                    },
                ],
            }
        )
        status_reader_calls = 0

        def status_reader() -> dict[str, object]:
            nonlocal status_reader_calls
            status_reader_calls += 1
            return {}

        service = CoreBrainIntegration(
            StubClient(mixed),
            system_status_reader=status_reader,
            device_list_reader=alex_app._authoritative_device_list,
            audit=lambda stage, level, details: None,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.object(
                alex_app.command_gateway,
                "request",
            ) as gateway,
            patch.object(
                alex_app.mqtt_client,
                "publish",
            ) as mqtt_publish,
        ):
            response = self.post(headers=CORE_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(status_reader_calls, 0)
        gateway.assert_not_called()
        mqtt_publish.assert_not_called()

    def test_assistant_success_claim_does_not_create_authoritative_success(self) -> None:
        service = CoreBrainIntegration(
            StubClient(
                brain_response(
                    assistant_text=(
                        "Đã bật relay_1 thành công và được xác nhận."
                    )
                )
            ),
            system_status_reader=alex_app._authoritative_system_status,
            device_list_reader=alex_app._authoritative_device_list,
            audit=lambda stage, level, details: None,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.object(
                alex_app.mqtt_client,
                "publish",
            ) as mqtt_publish,
        ):
            response = self.post(headers=CORE_AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tool_results"], [])
        mqtt_publish.assert_not_called()

    def test_app_audit_wiring_records_read_without_prompt_or_secret(self) -> None:
        service = CoreBrainIntegration(
            StubClient(brain_response("system_status")),
            system_status_reader=lambda: {"source": "core"},
            device_list_reader=lambda: {"items": []},
            audit=alex_app._audit_core_brain,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.object(alex_app, "add_event") as add_event,
        ):
            response = self.post(headers=CORE_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(add_event.call_count, 4)
        serialized = repr(add_event.call_args_list)
        self.assertIn("read_result", serialized)
        self.assertIn(VALID_BODY["request_id"], serialized)
        self.assertNotIn(VALID_BODY["user_text"], serialized)
        self.assertNotIn("ALEX_BRAIN_CLIENT_KEY", serialized)

    def test_app_audit_wiring_records_policy_rejection(self) -> None:
        service = CoreBrainIntegration(
            StubClient(
                brain_response("set_test_led", {"value": False})
            ),
            system_status_reader=lambda: {},
            device_list_reader=lambda: {},
            audit=alex_app._audit_core_brain,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.object(alex_app, "add_event") as add_event,
        ):
            response = self.post(headers=CORE_AUTH)

        self.assertEqual(response.status_code, 200)
        serialized = repr(add_event.call_args_list)
        self.assertIn("policy_rejected", serialized)
        self.assertIn("tool_not_enabled_in_c4", serialized)

    def test_brain_credential_never_appears_in_core_response(self) -> None:
        secret = "server-brain-credential-must-not-leak"
        service = CoreBrainIntegration(
            StubClient(brain_response("list_devices")),
            system_status_reader=lambda: {},
            device_list_reader=lambda: {"items": []},
            audit=lambda stage, level, details: None,
        )
        with (
            patch.object(alex_app, "core_brain_integration", service),
            patch.dict(
                os.environ,
                {"ALEX_BRAIN_CLIENT_KEY": secret},
            ),
        ):
            response = self.post(headers=CORE_AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.text)


if __name__ == "__main__":
    unittest.main()
