from __future__ import annotations

import json
import unittest
from collections.abc import Callable

from alex_brain_client import BrainClientError
from alex_brain_integration import (
    C4_EXECUTION_ALLOWLIST,
    CoreBrainIntegration,
)
from alex_brain_tools import (
    TOOL_NAMES,
    BrainChatRequest,
    BrainChatResponse,
)


REQUEST = BrainChatRequest(
    request_id="req-c4-policy",
    user_text="Hãy đọc dữ liệu từ Core.",
)


def response_with(
    *tool_calls: dict[str, object],
    assistant_text: str = "Đề xuất từ Brain.",
) -> BrainChatResponse:
    return BrainChatResponse.model_validate(
        {
            "request_id": REQUEST.request_id,
            "assistant_text": assistant_text,
            "tool_calls": list(tool_calls),
        }
    )


class StubBrainClient:
    def __init__(
        self,
        response: object | None = None,
        error: BrainClientError | None = None,
    ) -> None:
        self.response = response or response_with()
        self.error = error
        self.requests: list[BrainChatRequest] = []

    def chat(self, request: BrainChatRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class AuditSpy:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def __call__(
        self,
        stage: str,
        level: str,
        details: dict[str, object],
    ) -> None:
        self.records.append(
            {"stage": stage, "level": level, "details": details}
        )


class ReaderSpy:
    def __init__(
        self,
        result: dict[str, object],
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self) -> dict[str, object]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class CoreBrainIntegrationTests(unittest.TestCase):
    def integration(
        self,
        response: object,
        *,
        status_reader: Callable[[], dict[str, object]] | None = None,
        device_reader: Callable[[], dict[str, object]] | None = None,
        audit: AuditSpy | None = None,
    ) -> tuple[
        CoreBrainIntegration,
        ReaderSpy | Callable[[], dict[str, object]],
        ReaderSpy | Callable[[], dict[str, object]],
        AuditSpy,
    ]:
        status = status_reader or ReaderSpy(
            {"source": "core", "mqtt": "connected"}
        )
        devices = device_reader or ReaderSpy(
            {"source": "core", "items": [{"node_id": "esp01"}]}
        )
        audit_spy = audit or AuditSpy()
        return (
            CoreBrainIntegration(
                StubBrainClient(response),
                system_status_reader=status,
                device_list_reader=devices,
                audit=audit_spy,
            ),
            status,
            devices,
            audit_spy,
        )

    def test_c4_allowlist_is_exact_and_separate_from_six_tool_registry(self) -> None:
        self.assertEqual(
            C4_EXECUTION_ALLOWLIST,
            ("system_status", "list_devices"),
        )
        self.assertEqual(
            TOOL_NAMES,
            (
                "system_status",
                "list_devices",
                "set_test_led",
                "set_room_mode",
                "run_safe_mission",
                "run_safe_automation",
            ),
        )
        self.assertNotEqual(C4_EXECUTION_ALLOWLIST, TOOL_NAMES)

    def test_system_status_uses_authoritative_core_reader(self) -> None:
        brain_text = "Mọi thứ đã thành công theo lời model."
        service, status, devices, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                assistant_text=brain_text,
            )
        )
        result = service.chat(REQUEST)

        self.assertEqual(result.assistant_text, brain_text)
        self.assertEqual(result.tool_results[0].status, "ok")
        self.assertEqual(
            result.tool_results[0].result,
            {"source": "core", "mqtt": "connected"},
        )
        self.assertNotEqual(
            result.tool_results[0].result,
            {"source": "brain"},
        )
        self.assertEqual(status.calls, 1)
        self.assertEqual(devices.calls, 0)

    def test_list_devices_uses_authoritative_core_reader(self) -> None:
        service, status, devices, _ = self.integration(
            response_with({"name": "list_devices", "arguments": {}})
        )
        result = service.chat(REQUEST)

        self.assertEqual(result.tool_results[0].status, "ok")
        self.assertEqual(
            result.tool_results[0].result,
            {"source": "core", "items": [{"node_id": "esp01"}]},
        )
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 1)

    def test_no_tool_proposal_performs_no_read(self) -> None:
        service, status, devices, _ = self.integration(response_with())
        result = service.chat(REQUEST)
        self.assertEqual(result.tool_results, [])
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)

    def test_each_c4_disabled_tool_is_rejected_without_execution(self) -> None:
        cases = (
            ("set_test_led", {"value": True}),
            ("set_room_mode", {"mode": "study"}),
            ("run_safe_mission", {"mission_id": "safe-study"}),
            (
                "run_safe_automation",
                {"automation_id": "safe-check"},
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                service, status, devices, audit = self.integration(
                    response_with(
                        {"name": name, "arguments": arguments}
                    )
                )
                result = service.chat(REQUEST)
                self.assertEqual(
                    result.tool_results[0].status,
                    "rejected",
                )
                self.assertEqual(
                    result.tool_results[0].reason,
                    "tool_not_enabled_in_c4",
                )
                self.assertEqual(status.calls, 0)
                self.assertEqual(devices.calls, 0)
                self.assertIn(
                    "policy_rejected",
                    [record["stage"] for record in audit.records],
                )

    def test_mixed_batch_is_atomically_rejected_before_read(self) -> None:
        service, status, devices, _ = self.integration(
            response_with(
                {"name": "system_status", "arguments": {}},
                {"name": "set_test_led", "arguments": {"value": True}},
            )
        )
        result = service.chat(REQUEST)

        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)
        self.assertEqual(
            [item.status for item in result.tool_results],
            ["rejected", "rejected"],
        )
        self.assertEqual(
            [item.reason for item in result.tool_results],
            ["batch_rejected_in_c4", "tool_not_enabled_in_c4"],
        )

    def test_unknown_tool_rejects_whole_response_before_execution(self) -> None:
        malicious = {
            "request_id": REQUEST.request_id,
            "assistant_text": "Bypass",
            "tool_calls": [
                {"name": "system_status", "arguments": {}},
                {
                    "name": "mqtt_publish",
                    "arguments": {"topic": "relay_1"},
                },
            ],
        }
        service, status, devices, audit = self.integration(malicious)
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "invalid_brain_response")
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)
        self.assertEqual(
            audit.records[-1]["details"]["reason"],
            "invalid_brain_response",
        )

    def test_malformed_arguments_reject_before_execution(self) -> None:
        malformed = {
            "request_id": REQUEST.request_id,
            "assistant_text": "Invalid node injection",
            "tool_calls": [
                {
                    "name": "system_status",
                    "arguments": {"node_id": "relay_1"},
                }
            ],
        }
        service, status, devices, _ = self.integration(malformed)
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "invalid_brain_response")
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)

    def test_request_id_mismatch_is_rejected_by_core_revalidation(self) -> None:
        mismatch = {
            "request_id": "other-request",
            "assistant_text": "",
            "tool_calls": [],
        }
        service, status, devices, _ = self.integration(mismatch)
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "invalid_brain_response")
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)

    def test_assistant_success_claim_without_tool_is_not_core_success(self) -> None:
        service, status, devices, _ = self.integration(
            response_with(
                assistant_text="Đã bật relay và xác nhận thành công."
            )
        )
        result = service.chat(REQUEST)
        self.assertEqual(result.tool_results, [])
        self.assertNotIn('"status":"ok"', result.model_dump_json())
        self.assertEqual(status.calls, 0)
        self.assertEqual(devices.calls, 0)

    def test_authoritative_reader_failure_is_not_fake_success(self) -> None:
        failed_reader = ReaderSpy(
            {},
            error=RuntimeError("database details must not leak"),
        )
        service, _, _, audit = self.integration(
            response_with({"name": "system_status", "arguments": {}}),
            status_reader=failed_reader,
        )
        result = service.chat(REQUEST)
        self.assertEqual(result.tool_results[0].status, "error")
        self.assertEqual(
            result.tool_results[0].reason,
            "authoritative_read_failed",
        )
        self.assertIsNone(result.tool_results[0].result)
        self.assertNotIn("database details", result.model_dump_json())
        self.assertEqual(audit.records[-1]["details"]["outcome"], "error")

    def test_successful_read_has_correlated_bounded_audit(self) -> None:
        service, _, _, audit = self.integration(
            response_with({"name": "system_status", "arguments": {}})
        )
        service.chat(REQUEST)
        stages = [record["stage"] for record in audit.records]
        self.assertEqual(
            stages,
            [
                "request_accepted",
                "response_received",
                "read_execution",
                "read_result",
            ],
        )
        for record in audit.records:
            self.assertEqual(
                record["details"]["request_id"],
                REQUEST.request_id,
            )

    def test_rejected_proposal_audit_contains_no_secret_or_prompt(self) -> None:
        secret = "brain-super-secret"
        prompt = "full private user prompt"
        request = BrainChatRequest(
            request_id="req-audit-secret",
            user_text=prompt,
        )
        audit = AuditSpy()
        service = CoreBrainIntegration(
            StubBrainClient(
                BrainChatResponse.model_validate(
                    {
                        "request_id": request.request_id,
                        "assistant_text": "model raw text",
                        "tool_calls": [
                            {
                                "name": "set_room_mode",
                                "arguments": {"mode": "sleep"},
                            }
                        ],
                    }
                )
            ),
            system_status_reader=lambda: {},
            device_list_reader=lambda: {},
            audit=audit,
        )
        service.chat(request)
        serialized = json.dumps(audit.records)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(prompt, serialized)
        self.assertNotIn("model raw text", serialized)
        self.assertIn("policy_rejected", serialized)

    def test_client_failure_is_audited_and_remains_bounded(self) -> None:
        audit = AuditSpy()
        service = CoreBrainIntegration(
            StubBrainClient(
                error=BrainClientError("brain_unavailable")
            ),
            system_status_reader=lambda: {},
            device_list_reader=lambda: {},
            audit=audit,
        )
        with self.assertRaises(BrainClientError) as raised:
            service.chat(REQUEST)
        self.assertEqual(raised.exception.code, "brain_unavailable")
        self.assertEqual(
            audit.records[-1]["details"],
            {
                "request_id": REQUEST.request_id,
                "reason": "brain_unavailable",
            },
        )


if __name__ == "__main__":
    unittest.main()
