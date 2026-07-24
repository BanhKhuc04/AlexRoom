from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

import pytest

from alex_fast_response import (
    FastResponseReason,
    compact_fast_response,
    compose_fast_response,
)
from alex_intelligence import (
    IntelligenceDecision,
    IntelligenceRoute,
)
from alex_intent_planner import (
    IntentCertainty,
    IntentStep,
    plan_intelligence,
)
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
)
from alex_knowledge_query import (
    DeviceDetailQueryData,
    DeviceListQueryData,
    DeviceQueryData,
    KnowledgeQueryReason,
    KnowledgeQueryResult,
    KnowledgeQueryScope,
    MaintenanceQueryData,
    ServiceQueryData,
    SystemStatusQueryData,
)
from alex_safety import CommandGateway, SafetyPolicy


CAPTURED_AT = "2026-07-24T09:00:00+00:00"
OBSERVED_AT = "2026-07-24T08:59:00+00:00"
SOURCES = (KnowledgeSource.CORE_RUNTIME,)


def step_for(
    text: str,
    *,
    route: IntelligenceRoute = IntelligenceRoute.SYSTEM,
    tool: str = "system_status",
    certainty: IntentCertainty = IntentCertainty.EXACT,
    clarification: bool = False,
) -> IntentStep:
    allowed = (tool,) if tool in {"system_status", "list_devices"} else ()
    return IntentStep(
        index=0,
        original_text=text,
        normalized_text=text.casefold(),
        decision=IntelligenceDecision(
            route=route,
            matched=True,
            reason="test",
            allowed_tool_names=allowed,  # type: ignore[arg-type]
        ),
        certainty=certainty,
        requires_clarification=clarification,
        clarification_reason=None,
    )


def service(
    name: str,
    status: KnowledgeStatus,
    *,
    available: KnowledgeValue = KnowledgeValue.KNOWN_TRUE,
    stale: KnowledgeValue = KnowledgeValue.KNOWN_FALSE,
) -> ServiceQueryData:
    return ServiceQueryData(
        name=name,
        status=status,
        available=available,
        observed_at=OBSERVED_AT,
        stale=stale,
        sources=SOURCES,
    )


def maintenance(
    name: str,
    status: KnowledgeStatus,
    *,
    available: KnowledgeValue = KnowledgeValue.KNOWN_TRUE,
    stale: KnowledgeValue = KnowledgeValue.KNOWN_FALSE,
) -> MaintenanceQueryData:
    return MaintenanceQueryData(
        name=name,
        status=status,
        available=available,
        observed_at=OBSERVED_AT,
        stale=stale,
        sources=(KnowledgeSource.HEALTH_REPORT,),
    )


def system_knowledge(
    *,
    overall: KnowledgeStatus = KnowledgeStatus.HEALTHY,
    core: KnowledgeStatus = KnowledgeStatus.ONLINE,
    brain: KnowledgeStatus = KnowledgeStatus.ONLINE,
    core_stale: KnowledgeValue = KnowledgeValue.KNOWN_FALSE,
    brain_stale: KnowledgeValue = KnowledgeValue.KNOWN_FALSE,
    backup_status: KnowledgeStatus = KnowledgeStatus.HEALTHY,
    backup_available: KnowledgeValue = KnowledgeValue.KNOWN_TRUE,
    incomplete: bool = False,
) -> KnowledgeQueryResult:
    return KnowledgeQueryResult(
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        snapshot_captured_at=CAPTURED_AT,
        scope=KnowledgeQueryScope.SYSTEM_STATUS,
        data=SystemStatusQueryData(
            version="0.8.0",
            overall_status=overall,
            overall_sources=(KnowledgeSource.HEALTH_REPORT,),
            services=(
                service("brain", brain, stale=brain_stale),
                service("core", core, stale=core_stale),
            ),
            maintenance=(
                maintenance(
                    "backup",
                    backup_status,
                    available=backup_available,
                ),
                maintenance("health", KnowledgeStatus.HEALTHY),
            ),
        ),
        sources=(
            KnowledgeSource.CORE_RUNTIME,
            KnowledgeSource.HEALTH_REPORT,
        ),
        incomplete=incomplete,
        reason=(
            KnowledgeQueryReason.PARTIAL_KNOWLEDGE
            if incomplete
            else KnowledgeQueryReason.SELECTED_SYSTEM_STATUS
        ),
    )


def device(
    device_id: str,
    online: KnowledgeValue,
    *,
    stale: KnowledgeValue = KnowledgeValue.KNOWN_FALSE,
    available: KnowledgeValue = KnowledgeValue.KNOWN_TRUE,
    observed_at: str | None = OBSERVED_AT,
) -> DeviceQueryData:
    return DeviceQueryData(
        device_id=device_id,
        known=KnowledgeValue.KNOWN_TRUE,
        available=available,
        online=online,
        observed_at=observed_at,
        stale=stale,
        hardware_verified=KnowledgeValue.KNOWN_FALSE,
        sources=SOURCES,
    )


def device_detail_knowledge(
    item: DeviceQueryData | None,
    *,
    requested_id: str = "esp01",
    found: bool = True,
    incomplete: bool = False,
) -> KnowledgeQueryResult:
    return KnowledgeQueryResult(
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        snapshot_captured_at=CAPTURED_AT,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        data=DeviceDetailQueryData(
            requested_device_id=requested_id,
            found=found,
            device=item,
        ),
        sources=SOURCES,
        incomplete=incomplete,
        reason=(
            KnowledgeQueryReason.SELECTED_DEVICE_DETAIL
            if found and not incomplete
            else (
                KnowledgeQueryReason.DEVICE_NOT_FOUND
                if not found
                else KnowledgeQueryReason.PARTIAL_KNOWLEDGE
            )
        ),
    )


def device_list_knowledge(
    devices: tuple[DeviceQueryData, ...],
    *,
    incomplete: bool = False,
) -> KnowledgeQueryResult:
    return KnowledgeQueryResult(
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION,
        snapshot_captured_at=CAPTURED_AT,
        scope=KnowledgeQueryScope.DEVICE_LIST,
        data=DeviceListQueryData(devices=devices),
        sources=SOURCES,
        incomplete=incomplete,
        reason=(
            KnowledgeQueryReason.SELECTED_DEVICE_LIST
            if devices
            else KnowledgeQueryReason.NO_DEVICES
        ),
    )


def compose_system(
    knowledge: KnowledgeQueryResult,
):
    return compose_fast_response(
        step=step_for("ALEX có ổn không?"),
        knowledge=knowledge,
    )


def compose_device(
    knowledge: KnowledgeQueryResult,
):
    return compose_fast_response(
        step=step_for(
            "ESP01 online không?",
            tool="list_devices",
        ),
        knowledge=knowledge,
    )


def test_healthy_core_and_brain_produce_truthful_response() -> None:
    result = compose_system(system_knowledge())
    assert result.handled is True
    assert result.text == (
        "ALEX đang hoạt động bình thường. "
        "Core và Brain đều online."
    )


def test_unknown_brain_is_never_described_as_online() -> None:
    result = compose_system(
        system_knowledge(
            brain=KnowledgeStatus.UNKNOWN,
            brain_stale=KnowledgeValue.UNKNOWN,
            incomplete=True,
        )
    )
    assert result.handled is True
    assert result.text is not None
    assert "Trạng thái Brain hiện chưa xác định." in result.text
    assert "Core và Brain đều online" not in result.text


def test_unknown_overall_does_not_fake_healthy() -> None:
    result = compose_system(
        system_knowledge(
            overall=KnowledgeStatus.UNKNOWN,
            incomplete=True,
        )
    )
    assert result.handled is True
    assert result.text is not None
    assert "tổng thể của ALEX hiện chưa xác định" in result.text
    assert "hoạt động bình thường" not in result.text


def test_unavailable_backup_does_not_fake_healthy() -> None:
    result = compose_system(
        system_knowledge(
            backup_status=KnowledgeStatus.HEALTHY,
            backup_available=KnowledgeValue.UNAVAILABLE,
            incomplete=True,
        )
    )
    assert result.handled is True
    assert result.text is not None
    assert "Backup hiện không có dữ liệu khả dụng" in result.text
    assert "hoạt động bình thường" not in result.text


def test_online_device_with_fresh_data_is_current_wording() -> None:
    result = compose_device(
        device_detail_knowledge(
            device("esp01", KnowledgeValue.KNOWN_TRUE)
        )
    )
    assert result.handled is True
    assert result.text == "ESP01 đang online."
    assert result.warnings == ()


def test_offline_device_is_factual() -> None:
    result = compose_device(
        device_detail_knowledge(
            device("esp01", KnowledgeValue.KNOWN_FALSE)
        )
    )
    assert result.text == "ESP01 đang offline."


def test_unknown_device_online_state_remains_unknown() -> None:
    result = compose_device(
        device_detail_knowledge(
            device("esp01", KnowledgeValue.UNKNOWN),
            incomplete=True,
        )
    )
    assert result.handled is True
    assert result.text == (
        "Hiện chưa xác định được ESP01 có online hay không."
    )
    assert "offline" not in result.text


def test_device_not_found_is_deterministic_factual_response() -> None:
    knowledge = device_detail_knowledge(
        None,
        requested_id="esp99",
        found=False,
        incomplete=True,
    )
    left = compose_device(knowledge)
    right = compose_device(knowledge)
    assert left == right
    assert left.handled is True
    assert left.text == (
        "Không tìm thấy thiết bị ESP99 trong knowledge hiện tại."
    )


def test_stale_device_uses_explicit_caveat() -> None:
    result = compose_device(
        device_detail_knowledge(
            device(
                "esp01",
                KnowledgeValue.KNOWN_TRUE,
                stale=KnowledgeValue.KNOWN_TRUE,
            )
        )
    )
    assert result.text is not None
    assert "Dữ liệu gần nhất" in result.text
    assert "đánh dấu là cũ" in result.text
    assert "stale_data" in result.warnings


def test_unknown_device_freshness_is_not_called_fresh() -> None:
    result = compose_device(
        device_detail_knowledge(
            device(
                "esp01",
                KnowledgeValue.KNOWN_TRUE,
                stale=KnowledgeValue.UNKNOWN,
            )
        )
    )
    assert result.text is not None
    assert "Snapshot ghi nhận ESP01 online" in result.text
    assert "chưa xác định được độ mới" in result.text
    assert "freshness_unknown" in result.warnings


def test_observed_at_is_preserved_in_structured_metadata() -> None:
    result = compose_device(
        device_detail_knowledge(
            device("esp01", KnowledgeValue.KNOWN_TRUE)
        )
    )
    assert result.metadata.snapshot_captured_at == CAPTURED_AT
    assert result.metadata.observations[0] == ("esp01", OBSERVED_AT)


def test_device_list_summarizes_known_states() -> None:
    result = compose_device(
        device_list_knowledge(
            (
                device("esp01", KnowledgeValue.KNOWN_TRUE),
                device("esp02", KnowledgeValue.KNOWN_FALSE),
            )
        )
    )
    assert result.text == (
        "Có 2 thiết bị trong snapshot: "
        "ESP01 online, ESP02 offline."
    )


def test_device_list_unknown_state_never_becomes_offline() -> None:
    result = compose_device(
        device_list_knowledge(
            (device("esp03", KnowledgeValue.UNKNOWN),),
            incomplete=True,
        )
    )
    assert result.text is not None
    assert "ESP03 chưa xác định trạng thái" in result.text
    assert "offline" not in result.text


def test_restricted_device_state_never_becomes_offline() -> None:
    result = compose_device(
        device_list_knowledge(
            (
                device(
                    "esp04",
                    KnowledgeValue.RESTRICTED,
                    available=KnowledgeValue.RESTRICTED,
                ),
            )
        )
    )
    assert result.text is not None
    assert "bị giới hạn truy cập" in result.text
    assert "offline" not in result.text


def test_system_response_does_not_dump_unnecessary_knowledge() -> None:
    encoded = json.dumps(
        compose_system(system_knowledge()).to_compact_dict()
    )
    assert "device" not in encoded
    assert "capabilities" not in encoded
    assert "relay_1" not in encoded


def test_step_requiring_clarification_is_declined() -> None:
    result = compose_fast_response(
        step=step_for(
            "bật nó lên",
            certainty=IntentCertainty.UNKNOWN,
            clarification=True,
        ),
        knowledge=system_knowledge(),
    )
    assert result.handled is False
    assert result.text is None
    assert (
        result.reason
        is FastResponseReason.STEP_REQUIRES_CLARIFICATION
    )


def test_unknown_certainty_is_declined() -> None:
    result = compose_fast_response(
        step=step_for(
            "không rõ",
            certainty=IntentCertainty.UNKNOWN,
        ),
        knowledge=system_knowledge(),
    )
    assert result.handled is False
    assert result.reason is FastResponseReason.UNKNOWN_INTENT_CERTAINTY


@pytest.mark.parametrize(
    "text,route",
    [
        ("giải thích tại sao hệ thống chậm", IntelligenceRoute.LLM),
        ("mấy giờ rồi", IntelligenceRoute.TIME),
        ("thời tiết Hà Nội", IntelligenceRoute.WEATHER),
        ("2 + 2", IntelligenceRoute.CALCULATOR),
    ],
)
def test_non_system_routes_are_declined(
    text: str,
    route: IntelligenceRoute,
) -> None:
    result = compose_fast_response(
        step=step_for(text, route=route, tool=""),
        knowledge=system_knowledge(),
    )
    assert result.handled is False
    assert result.text is None
    assert result.reason is FastResponseReason.UNSUPPORTED_ROUTE


@pytest.mark.parametrize(
    "text",
    [
        "bật đèn test",
        "tắt đèn test",
        "bật relay_1",
        "đổi room mode",
        "chạy mission",
    ],
)
def test_mutation_steps_never_create_fast_success(
    text: str,
) -> None:
    step = plan_intelligence(text).steps[0]
    result = compose_fast_response(
        step=step,
        knowledge=system_knowledge(),
    )
    assert result.handled is False
    assert result.text is None
    assert result.reason is FastResponseReason.UNSUPPORTED_ROUTE


def test_unsupported_future_schema_is_declined() -> None:
    knowledge = replace(
        system_knowledge(),
        knowledge_schema_version=KNOWLEDGE_SCHEMA_VERSION + 1,
    )
    result = compose_system(knowledge)
    assert result.handled is False
    assert (
        result.reason
        is FastResponseReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
    )
    assert result.incomplete is True


def test_incompatible_step_and_knowledge_scope_is_declined() -> None:
    result = compose_fast_response(
        step=step_for("ALEX có ổn không?"),
        knowledge=device_list_knowledge(
            (device("esp01", KnowledgeValue.KNOWN_TRUE),)
        ),
    )
    assert result.handled is False
    assert result.reason is FastResponseReason.INCOMPATIBLE_SCOPE


def test_entirely_unknown_system_knowledge_is_declined() -> None:
    knowledge = system_knowledge(
        overall=KnowledgeStatus.UNKNOWN,
        core=KnowledgeStatus.UNKNOWN,
        brain=KnowledgeStatus.UNKNOWN,
        incomplete=True,
    )
    assert isinstance(knowledge.data, SystemStatusQueryData)
    knowledge = replace(
        knowledge,
        data=replace(
            knowledge.data,
            maintenance=(
                maintenance("backup", KnowledgeStatus.UNKNOWN),
                maintenance("health", KnowledgeStatus.UNKNOWN),
            ),
        ),
    )
    result = compose_system(knowledge)
    assert result.handled is False
    assert result.reason is FastResponseReason.INSUFFICIENT_KNOWLEDGE


def test_result_and_nested_metadata_are_immutable() -> None:
    result = compose_system(system_knowledge())
    with pytest.raises(FrozenInstanceError):
        result.handled = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.metadata.snapshot_captured_at = "changed"  # type: ignore[misc]
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.metadata.observations, tuple)


def test_result_is_deterministic() -> None:
    step = step_for("ALEX có ổn không?")
    knowledge = system_knowledge()
    left = compose_fast_response(step=step, knowledge=knowledge)
    right = compose_fast_response(step=step, knowledge=knowledge)
    assert left == right


def test_compact_result_is_strict_json_serializable() -> None:
    result = compose_system(system_knowledge())
    compact = compact_fast_response(result)
    encoded = json.dumps(compact, allow_nan=False)
    assert json.loads(encoded) == compact


def test_result_does_not_expose_unselected_secret_text() -> None:
    secret = "NEVER_EXPOSE_THIS_SECRET"
    knowledge = system_knowledge()
    assert isinstance(knowledge.data, SystemStatusQueryData)
    knowledge = replace(
        knowledge,
        data=replace(knowledge.data, version=secret),
    )
    result = compose_system(knowledge)
    encoded = json.dumps(result.to_compact_dict())
    assert secret not in encoded
    assert "authorization" not in encoded.casefold()
    assert "password" not in encoded.casefold()


def test_composer_does_not_execute_network_ollama_or_hardware() -> None:
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("urllib.request.urlopen", side_effect=AssertionError("network")),
        patch.object(
            SafetyPolicy,
            "authorize",
            side_effect=AssertionError("safety execution"),
        ),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("hardware execution"),
        ),
    ):
        result = compose_device(
            device_detail_knowledge(
                device("esp01", KnowledgeValue.KNOWN_TRUE)
            )
        )
    assert result.handled is True
