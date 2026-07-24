from __future__ import annotations

import ast
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "unit-test-api-key")
os.environ.setdefault("ALEX_SIMULATOR", "0")
os.environ.setdefault("ALEX_DATABASE_PATH", "data/unit-test-app.db")
os.environ.setdefault("ALEX_BRAIN_ENABLED", "false")

import app as alex_app  # noqa: E402
import alex_intelligence_fast_path as fast_path_module  # noqa: E402
from _brain_service_test_client import AsgiTestClient  # noqa: E402
from alex_brain_integration import CoreBrainChatResponse  # noqa: E402
from alex_fast_response import compose_fast_response  # noqa: E402
from alex_intelligence_fast_path import (  # noqa: E402
    FAST_PATH_ELIGIBLE_SCOPES,
    FastPathReason,
    FastPathStatus,
    IntelligenceFastPathResult,
    evaluate_intelligence_fast_path,
    intelligence_fast_path_enabled,
)
from alex_intelligence_runtime import (  # noqa: E402
    RuntimeOutcome,
    decide_intelligence_runtime,
)
from alex_knowledge import build_system_knowledge_snapshot  # noqa: E402
from alex_knowledge_contracts import (  # noqa: E402
    KnowledgeSource,
    KnowledgeValue,
)
from alex_knowledge_query import (  # noqa: E402
    DeviceDetailQueryData,
    DeviceQueryData,
    KnowledgeQueryReason,
    KnowledgeQueryResult,
    KnowledgeQueryScope,
)
from alex_safety import CapabilityRegistry, SafetyPolicy  # noqa: E402


CAPTURED_AT = "2026-07-24T10:00:00+00:00"
OBSERVED_AT = "2026-07-24T09:59:00+00:00"
REQUEST_ID = "req-fast-path"
AUTH = {"X-ALEX-Key": alex_app.ALEX_API_KEY}
CLIENT = AsgiTestClient(alex_app.app)
MODULE_PATH = Path(fast_path_module.__file__)


def knowledge_snapshot(
    *,
    brain_status: str = "online",
    brain_available: object = True,
    device_online: object = True,
    include_device: bool = True,
    backup_status: str = "healthy",
    backup_available: object = True,
):
    devices: object = {}
    if include_device:
        devices = {
            "esp01": {
                "node_id": "esp01",
                "connection": (
                    "online"
                    if device_online is True
                    else (
                        "offline"
                        if device_online is False
                        else "unknown"
                    )
                ),
                "online": device_online,
                "last_seen_at": OBSERVED_AT,
                "verification_status": "basic_physical_validated",
                "hardware_verified": False,
                "capabilities": {
                    "test_led": {
                        "available": True,
                        "command_allowed": True,
                    },
                    "relay_1": {
                        "availability": "restricted",
                        "verification_status": "restricted",
                        "command_allowed": False,
                    },
                },
                "source": "hardware_registry",
            }
        }
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        overall_status="healthy",
        health_report={
            "available": True,
            "status": "healthy",
            "stale": False,
            "generated_at": OBSERVED_AT,
            "report": {
                "status": "healthy",
                "generated_at": OBSERVED_AT,
                "checks": {
                    "backup": {
                        "status": backup_status,
                        "available": backup_available,
                        "stale": False,
                    },
                    "update": {"status": "unknown"},
                },
            },
        },
        services={
            "core": {
                "status": "online",
                "available": True,
                "stale": False,
                "source": "core_runtime",
            },
            "brain": {
                "status": brain_status,
                "available": brain_available,
                "stale": False,
                "observed_at": OBSERVED_AT,
                "source": "core_runtime",
            },
        },
        devices=devices,
        runtime={
            "room_mode": "home",
            "simulator": False,
            "source": "core_runtime",
        },
    )


class StubLegacyService:
    def __init__(self, text: str = "Legacy Brain response.") -> None:
        self.text = text
        self.calls = 0

    def chat(self, request):
        self.calls += 1
        return CoreBrainChatResponse(
            request_id=request.request_id,
            assistant_text=self.text,
        )


def request(
    user_text: str,
    *,
    fast_enabled: bool,
    shadow_enabled: bool = False,
    snapshot=None,
    service: StubLegacyService | None = None,
):
    legacy = service or StubLegacyService()
    source = snapshot if snapshot is not None else knowledge_snapshot()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            fast_enabled,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            shadow_enabled,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=source,
        ),
        patch.object(alex_app, "core_brain_integration", legacy),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": user_text,
            },
        )
    return response, legacy


def local_evaluation(
    user_text: str,
    *,
    snapshot=None,
    evaluator=decide_intelligence_runtime,
) -> IntelligenceFastPathResult:
    source = snapshot if snapshot is not None else knowledge_snapshot()
    return evaluate_intelligence_fast_path(
        enabled=True,
        user_text=user_text,
        snapshot_factory=lambda: source,
        now_monotonic=0,
        evaluator=evaluator,
    )


def test_flag_absent_is_disabled() -> None:
    assert intelligence_fast_path_enabled({}) is False


@pytest.mark.parametrize(
    "value",
    ["false", "0", "no", "off", "", "enabled", "2"],
)
def test_false_and_invalid_flag_values_are_disabled(value: str) -> None:
    assert intelligence_fast_path_enabled(
        {"ALEX_INTELLIGENCE_FAST_PATH_ENABLED": value}
    ) is False


@pytest.mark.parametrize(
    "value",
    ["1", "true", "TRUE", " yes ", "On"],
)
def test_true_flag_values_are_enabled(value: str) -> None:
    assert intelligence_fast_path_enabled(
        {"ALEX_INTELLIGENCE_FAST_PATH_ENABLED": value}
    ) is True


def test_fast_and_shadow_flags_are_independent() -> None:
    environment = {
        "ALEX_INTELLIGENCE_SHADOW_ENABLED": "true",
        "ALEX_INTELLIGENCE_FAST_PATH_ENABLED": "false",
    }
    assert intelligence_fast_path_enabled(environment) is False


def test_disabled_evaluator_is_lazy() -> None:
    factory = Mock(side_effect=AssertionError("no snapshot"))
    evaluator = Mock(side_effect=AssertionError("no runtime"))
    result = evaluate_intelligence_fast_path(
        enabled=False,
        user_text="ALEX có ổn không?",
        snapshot_factory=factory,
        now_monotonic=0,
        evaluator=evaluator,
    )
    assert result.status is FastPathStatus.DISABLED
    factory.assert_not_called()
    evaluator.assert_not_called()


def test_exact_eligibility_allowlist() -> None:
    assert tuple(FAST_PATH_ELIGIBLE_SCOPES) == (
        KnowledgeQueryScope.SYSTEM_STATUS,
        KnowledgeQueryScope.DEVICE_LIST,
        KnowledgeQueryScope.DEVICE_DETAIL,
    )


def test_fast_off_system_query_calls_legacy_once() -> None:
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=False,
    )
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert legacy.calls == 1


def test_fast_on_system_status_skips_brain() -> None:
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert response.json()["assistant_text"].startswith("ALEX đang")
    assert legacy.calls == 0


def test_fast_response_uses_current_public_schema() -> None:
    response, _ = request(
        "ALEX có ổn không?",
        fast_enabled=True,
    )
    assert set(response.json()) == {
        "request_id",
        "assistant_text",
        "proposed_tool_calls",
        "tool_results",
    }


def test_fast_response_preserves_request_id() -> None:
    response, _ = request(
        "ALEX có ổn không?",
        fast_enabled=True,
    )
    assert response.json()["request_id"] == REQUEST_ID


def test_fast_response_has_no_tool_proposal_or_result() -> None:
    response, _ = request(
        "ALEX có ổn không?",
        fast_enabled=True,
    )
    body = response.json()
    assert body["proposed_tool_calls"] == []
    assert body["tool_results"] == []


def test_device_list_skips_brain() -> None:
    response, legacy = request(
        "liệt kê thiết bị",
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert "Có 1 thiết bị" in response.json()["assistant_text"]
    assert legacy.calls == 0


def test_device_detail_skips_brain() -> None:
    response, legacy = request(
        "ESP01 online không?",
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert "ESP01 online" in response.json()["assistant_text"]
    assert legacy.calls == 0


def test_unknown_device_uses_existing_factual_wording() -> None:
    response, legacy = request(
        "trạng thái thiết bị ESP99",
        fast_enabled=True,
    )
    assert response.json()["assistant_text"] == (
        "Không tìm thấy thiết bị ESP99 trong knowledge hiện tại."
    )
    assert legacy.calls == 0


def _device_decision_with_stale(
    stale: KnowledgeValue,
):
    source = knowledge_snapshot()
    base = decide_intelligence_runtime(
        user_text="ESP01 online không?",
        snapshot=source,
        circuit_state=fast_path_module.BrainCircuitBreakerState(),
        circuit_config=fast_path_module.BrainCircuitBreakerConfig(),
        now_monotonic=0,
    )
    assert base.selected_step is not None
    knowledge = KnowledgeQueryResult(
        knowledge_schema_version=source.schema_version,
        snapshot_captured_at=source.captured_at,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        data=DeviceDetailQueryData(
            requested_device_id="esp01",
            found=True,
            device=DeviceQueryData(
                device_id="esp01",
                known=KnowledgeValue.KNOWN_TRUE,
                available=KnowledgeValue.KNOWN_TRUE,
                online=KnowledgeValue.KNOWN_TRUE,
                observed_at=OBSERVED_AT,
                stale=stale,
                hardware_verified=KnowledgeValue.KNOWN_FALSE,
                sources=(KnowledgeSource.HARDWARE_REGISTRY,),
            ),
        ),
        sources=(KnowledgeSource.HARDWARE_REGISTRY,),
        incomplete=False,
        reason=KnowledgeQueryReason.SELECTED_DEVICE_DETAIL,
    )
    composed = compose_fast_response(
        step=base.selected_step,
        knowledge=knowledge,
    )
    return replace(
        base,
        fast_response=composed,
        response_text=composed.text,
    )


def test_stale_device_wording_is_preserved_exactly() -> None:
    decision = _device_decision_with_stale(KnowledgeValue.KNOWN_TRUE)
    result = local_evaluation(
        "ESP01 online không?",
        evaluator=lambda **_kwargs: decision,
    )
    assert result.assistant_text == (
        "Dữ liệu gần nhất cho thấy ESP01 online, "
        "nhưng thông tin này đã được đánh dấu là cũ."
    )


def test_unknown_freshness_wording_is_preserved_exactly() -> None:
    response, _ = request(
        "ESP01 online không?",
        fast_enabled=True,
    )
    assert response.json()["assistant_text"] == (
        "Snapshot ghi nhận ESP01 online, "
        "nhưng chưa xác định được độ mới của dữ liệu."
    )


def test_unknown_brain_is_not_described_as_online() -> None:
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=True,
        snapshot=knowledge_snapshot(
            brain_status="unknown",
            brain_available="unknown",
        ),
    )
    text = response.json()["assistant_text"]
    assert "Trạng thái Brain hiện chưa xác định." in text
    assert "Brain đều online" not in text
    assert legacy.calls == 0


def test_unavailable_backup_is_not_described_as_healthy() -> None:
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=True,
        snapshot=knowledge_snapshot(
            backup_status="healthy",
            backup_available=False,
        ),
    )
    text = response.json()["assistant_text"]
    assert "Backup hiện không có dữ liệu khả dụng." in text
    assert "hoạt động bình thường" not in text
    assert legacy.calls == 0


@pytest.mark.parametrize(
    "prompt",
    [
        "Giải thích vì sao ALEX chậm",
        "Mấy giờ rồi?",
        "Thời tiết Hà Nội thế nào?",
        "2 + 2",
        "bật nó lên",
        "trạng thái ALEX rồi liệt kê thiết bị",
    ],
)
def test_ineligible_requests_fall_back_once(prompt: str) -> None:
    response, legacy = request(prompt, fast_enabled=True)
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert legacy.calls == 1


@pytest.mark.parametrize(
    "prompt",
    [
        "bật đèn test",
        "tắt đèn test",
        "bật relay_1",
        "đổi room mode",
        "chạy mission học tập",
        "chạy automation an toàn",
    ],
)
def test_mutations_are_legacy_only(prompt: str) -> None:
    response, legacy = request(prompt, fast_enabled=True)
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert legacy.calls == 1


def test_relay_safety_policy_is_unchanged() -> None:
    policy = SafetyPolicy(CapabilityRegistry(), simulator_mode=False)
    decision = policy.authorize("esp01", "relay_1", "on")
    assert decision.allowed is False
    assert decision.reason == "restricted_capability"


def test_fast_path_exception_falls_back_once() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "_evaluate_intelligence_fast_path",
            side_effect=RuntimeError("local failure"),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert service.calls == 1


def test_malformed_fast_path_result_falls_back_once() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "_evaluate_intelligence_fast_path",
            return_value={"handled": True},
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert service.calls == 1


def test_invalid_local_response_contract_falls_back_once() -> None:
    service = StubLegacyService()
    invalid = IntelligenceFastPathResult(
        enabled=True,
        status=FastPathStatus.HANDLED,
        reason=FastPathReason.READ_ONLY_RESPONSE,
        outcome=RuntimeOutcome.RESPOND_FAST,
        scope=KnowledgeQueryScope.SYSTEM_STATUS,
        brain_skipped=True,
        assistant_text="x" * 5000,
    )
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "_evaluate_intelligence_fast_path",
            return_value=invalid,
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert service.calls == 1


def test_snapshot_exception_falls_back_once() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            side_effect=RuntimeError("snapshot failed"),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert service.calls == 1


def test_runtime_exception_falls_back_once() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "evaluate_intelligence_fast_path",
            side_effect=RuntimeError("runtime failed"),
        ),
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert service.calls == 1


def test_malformed_runtime_result_declines_safely() -> None:
    result = local_evaluation(
        "ALEX có ổn không?",
        evaluator=lambda **_kwargs: {"outcome": "respond_fast"},
    )
    assert result.status is FastPathStatus.FAST_PATH_ERROR
    assert result.brain_skipped is False


def test_future_schema_falls_back_once() -> None:
    source = knowledge_snapshot()
    object.__setattr__(source, "schema_version", 999)
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=True,
        snapshot=source,
    )
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert legacy.calls == 1


def test_fast_response_decline_falls_back_once() -> None:
    empty = build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
    )
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=True,
        snapshot=empty,
    )
    assert response.json()["assistant_text"] == "Legacy Brain response."
    assert legacy.calls == 1


@pytest.mark.parametrize(
    ("fast_enabled", "shadow_enabled", "expected_local"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, True),
        (True, True, True),
    ],
)
def test_flag_interaction_matrix(
    fast_enabled: bool,
    shadow_enabled: bool,
    expected_local: bool,
) -> None:
    response, legacy = request(
        "ALEX có ổn không?",
        fast_enabled=fast_enabled,
        shadow_enabled=shadow_enabled,
    )
    assert response.status_code == 200
    assert legacy.calls == (0 if expected_local else 1)
    assert (
        response.json()["assistant_text"] != "Legacy Brain response."
    ) is expected_local


def test_both_flags_reuse_one_runtime_evaluation() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(
            alex_app,
            "evaluate_intelligence_fast_path",
            wraps=evaluate_intelligence_fast_path,
        ) as evaluator,
        patch.object(
            alex_app,
            "_observe_intelligence_shadow",
        ) as separate_shadow,
        patch.object(alex_app, "core_brain_integration", service),
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ALEX có ổn không?",
            },
        )
    assert response.status_code == 200
    assert evaluator.call_count == 1
    separate_shadow.assert_not_called()
    assert service.calls == 0


def test_both_flags_do_not_execute_duplicate_action() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(alex_app.command_gateway, "request") as gateway,
        patch.object(alex_app.mqtt_client, "publish") as mqtt_publish,
        patch.object(alex_app.mission_executor, "run") as mission,
        patch.object(
            alex_app.automation_executor,
            "evaluate",
        ) as automation,
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "bật relay_1",
            },
        )
    assert response.status_code == 200
    assert service.calls == 1
    gateway.assert_not_called()
    mqtt_publish.assert_not_called()
    mission.assert_not_called()
    automation.assert_not_called()


def test_fast_response_http_contract_is_compatible() -> None:
    response, _ = request(
        "liệt kê thiết bị",
        fast_enabled=True,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    CoreBrainChatResponse.model_validate(response.json())


def test_fast_result_and_log_exclude_private_data(caplog) -> None:
    caplog.set_level(
        "INFO",
        logger="alex.intelligence.fast_path",
    )
    result = local_evaluation(
        "Giải thích token=private-secret",
    )
    serialized = json.dumps(result.to_compact_dict()).lower()
    record = next(
        item
        for item in caplog.records
        if item.name == "alex.intelligence.fast_path"
    )
    logged = json.dumps(record.fast_path).lower()
    for forbidden in (
        "private-secret",
        "user_text",
        "authorization",
        "api_key",
        "password",
        "chain-of-thought",
        "snapshot",
        "assistant_text",
    ):
        assert forbidden not in serialized
        assert forbidden not in logged


def test_public_fast_response_does_not_echo_secret_or_auth_text() -> None:
    response, legacy = request(
        "ALEX có ổn không? Authorization=Bearer-private-secret",
        fast_enabled=True,
    )
    serialized = response.text.lower()
    assert "bearer-private-secret" not in serialized
    assert "authorization" not in serialized
    assert "chain-of-thought" not in serialized
    assert legacy.calls == 0


def test_fast_path_never_claims_action_success() -> None:
    result = local_evaluation("bật đèn test")
    serialized = json.dumps(
        result.to_compact_dict(),
        ensure_ascii=False,
    ).lower()
    assert "đã bật" not in serialized
    assert "đã tắt" not in serialized
    assert "đã thực hiện" not in serialized


def test_fast_path_module_has_no_execution_or_io_authority() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = {
        (
            node.module
            if isinstance(node, ast.ImportFrom)
            else alias.name
        )
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {
            "app",
            "alex_brain",
            "alex_brain_client",
            "alex_hardware",
            "alex_orchestration",
            "alex_safety",
            "alex_store",
            "paho",
            "sqlite3",
        }
    )


def test_fast_path_module_has_no_executor_mqtt_or_db_calls() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {
            "publish",
            "request",
            "execute",
            "run",
            "connect",
            "commit",
            "put_record",
            "add_audit",
        }
    )


def test_eligible_request_does_not_reach_any_action_boundary() -> None:
    service = StubLegacyService()
    with (
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_FAST_PATH_ENABLED",
            True,
        ),
        patch.object(
            alex_app,
            "ALEX_INTELLIGENCE_SHADOW_ENABLED",
            False,
        ),
        patch.object(
            alex_app,
            "_build_intelligence_shadow_snapshot",
            return_value=knowledge_snapshot(),
        ),
        patch.object(alex_app, "core_brain_integration", service),
        patch.object(alex_app.command_gateway, "request") as gateway,
        patch.object(alex_app.mqtt_client, "publish") as mqtt_publish,
        patch.object(alex_app.mission_executor, "run") as mission,
        patch.object(
            alex_app.automation_executor,
            "evaluate",
        ) as automation,
    ):
        response = CLIENT.post(
            "/api/v1/brain/chat",
            headers=AUTH,
            json_body={
                "request_id": REQUEST_ID,
                "user_text": "ESP01 online không?",
            },
        )
    assert response.status_code == 200
    assert service.calls == 0
    gateway.assert_not_called()
    mqtt_publish.assert_not_called()
    mission.assert_not_called()
    automation.assert_not_called()


def test_disabled_path_1000_handler_calls_avoid_snapshot_and_runtime() -> None:
    factory = Mock()
    started = time.perf_counter()
    for _ in range(1000):
        evaluate_intelligence_fast_path(
            enabled=False,
            user_text="ALEX có ổn không?",
            snapshot_factory=factory,
            now_monotonic=0,
        )
    assert time.perf_counter() - started < 1.0
    factory.assert_not_called()


def test_1000_eligible_local_evaluations_are_lightweight() -> None:
    source = knowledge_snapshot()
    started = time.perf_counter()
    for _ in range(1000):
        result = evaluate_intelligence_fast_path(
            enabled=True,
            user_text="ALEX có ổn không?",
            snapshot_factory=lambda: source,
            now_monotonic=0,
        )
        assert result.handled
    assert time.perf_counter() - started < 5.0
