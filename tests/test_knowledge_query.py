from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from alex_intelligence import (
    IntelligenceDecision,
    IntelligenceRoute,
    route_intelligence,
)
from alex_knowledge import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeValue,
    build_system_knowledge_snapshot,
)
from alex_knowledge_query import (
    DeviceDetailQueryData,
    DeviceListQueryData,
    KnowledgeQueryReason,
    KnowledgeQueryScope,
    SystemStatusQueryData,
    compact_knowledge_query,
    query_knowledge,
)
from alex_safety import CapabilityRegistry, CommandGateway, SafetyPolicy


CAPTURED_AT = "2026-07-24T09:00:00+00:00"
OBSERVED_AT = "2026-07-24T08:59:00+00:00"
SYSTEM_DECISION = IntelligenceDecision(
    route=IntelligenceRoute.SYSTEM,
    matched=True,
    reason="test_system",
    allowed_tool_names=("system_status",),
)
DEVICE_DECISION = IntelligenceDecision(
    route=IntelligenceRoute.SYSTEM,
    matched=True,
    reason="test_devices",
    allowed_tool_names=("list_devices",),
)


def device_input(
    device_id: str,
    *,
    online: bool = True,
    observed_at: str | None = OBSERVED_AT,
) -> dict[str, object]:
    registry = CapabilityRegistry().public_snapshot()["esp01"]
    result: dict[str, object] = {
        **registry,
        "node_id": device_id,
        "connection": "online" if online else "offline",
        "reported_state": {
            "test_led": {"on": True},
            "relays": {
                "1": "OFF",
                "2": "OFF",
                "3": "OFF",
                "4": "OFF",
            },
        },
        "source": "mqtt",
    }
    if observed_at is not None:
        result["observed_at"] = observed_at
    return result


def build_snapshot(
    *,
    devices: object = None,
    health_stale: bool = True,
):
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        health_report={
            "available": True,
            "stale": health_stale,
            "status": "healthy",
            "report": {
                "generated_at": OBSERVED_AT,
                "status": "healthy",
                "checks": {
                    "backup": {
                        "status": "healthy",
                        "stale": False,
                    },
                    "update": {"status": "unknown"},
                },
            },
        },
        services={
            "core": {
                "status": "online",
                "observed_at": OBSERVED_AT,
                "stale": False,
                "source": "core_runtime",
            },
            "brain": {
                "status": "unknown",
                "source": "core_runtime",
            },
        },
        devices=(
            {
                "esp01": device_input("esp01"),
                "esp02": device_input("esp02", online=False),
            }
            if devices is None
            else devices
        ),
    )


def test_system_status_selects_only_relevant_fields() -> None:
    result = query_knowledge(
        build_snapshot(),
        route_intelligence("ALEX có ổn không?"),
        "ALEX có ổn không?",
    )
    assert result.scope is KnowledgeQueryScope.SYSTEM_STATUS
    assert isinstance(result.data, SystemStatusQueryData)
    assert result.data.version == "0.8.0"
    assert result.data.overall_status.value == "healthy"
    assert [item.name for item in result.data.services] == ["brain", "core"]
    assert [item.name for item in result.data.maintenance] == [
        "backup",
        "health",
    ]


def test_system_query_contains_no_devices_or_capabilities() -> None:
    compact = query_knowledge(
        build_snapshot(),
        SYSTEM_DECISION,
        "trạng thái ALEX",
    ).to_compact_dict()
    encoded = json.dumps(compact)
    assert "devices" not in compact["data"]
    assert "capabilities" not in encoded
    assert "relay_1" not in encoded


def test_device_list_contains_compact_summaries() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "liệt kê thiết bị",
    )
    assert result.scope is KnowledgeQueryScope.DEVICE_LIST
    assert isinstance(result.data, DeviceListQueryData)
    assert [item.device_id for item in result.data.devices] == [
        "esp01",
        "esp02",
    ]
    assert result.data.devices[0].online is KnowledgeValue.KNOWN_TRUE
    assert result.data.devices[1].online is KnowledgeValue.KNOWN_FALSE


def test_device_list_does_not_dump_capabilities() -> None:
    compact = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "có những thiết bị nào?",
    ).to_compact_dict()
    assert "capabilities" not in json.dumps(compact)
    assert "reported_state" not in json.dumps(compact)


def test_specific_device_query_selects_only_esp01() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    assert result.scope is KnowledgeQueryScope.DEVICE_DETAIL
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.found is True
    assert result.data.device is not None
    assert result.data.device.device_id == "esp01"
    assert "esp02" not in json.dumps(result.to_compact_dict())


def test_device_id_matching_is_case_insensitive_but_exact() -> None:
    for text in ("ESP01 online không?", "esp01 online không?"):
        result = query_knowledge(
            build_snapshot(),
            DEVICE_DECISION,
            text,
        )
        assert isinstance(result.data, DeviceDetailQueryData)
        assert result.data.found is True
        assert result.data.device is not None
        assert result.data.device.device_id == "esp01"


def test_unknown_esp99_is_not_fabricated() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP99 online không?",
    )
    assert result.scope is KnowledgeQueryScope.DEVICE_DETAIL
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.requested_device_id == "esp99"
    assert result.data.found is False
    assert result.data.device is None
    assert result.incomplete is True
    assert result.reason is KnowledgeQueryReason.DEVICE_NOT_FOUND


def test_esp1_is_not_fuzzy_mapped_to_esp01() -> None:
    result = query_knowledge(
        build_snapshot(devices={"esp01": device_input("esp01")}),
        DEVICE_DECISION,
        "ESP1 online không?",
    )
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.requested_device_id == "esp1"
    assert result.data.found is False
    assert "esp01" not in json.dumps(result.to_compact_dict())


def test_hardware_verified_false_is_preserved() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.device is not None
    assert result.data.device.hardware_verified is KnowledgeValue.KNOWN_FALSE
    assert result.to_compact_dict()["data"]["device"][
        "hardware_verified"
    ] is False


def test_restricted_relays_remain_restricted_not_off_or_available() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.restricted_capabilities == (
        "relay_1",
        "relay_2",
        "relay_3",
        "relay_4",
    )
    restricted = result.to_compact_dict()["data"]["restricted_capabilities"]
    assert restricted == {
        "relay_1": "restricted",
        "relay_2": "restricted",
        "relay_3": "restricted",
        "relay_4": "restricted",
    }
    assert "OFF" not in json.dumps(result.to_compact_dict())
    assert "available" not in restricted.values()


def test_device_observed_at_is_preserved() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.device is not None
    assert result.data.device.observed_at == OBSERVED_AT
    assert result.snapshot_captured_at == CAPTURED_AT


def test_stale_true_and_false_are_preserved_for_system_knowledge() -> None:
    result = query_knowledge(
        build_snapshot(health_stale=True),
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    assert isinstance(result.data, SystemStatusQueryData)
    services = {item.name: item for item in result.data.services}
    maintenance = {item.name: item for item in result.data.maintenance}
    assert services["core"].stale is KnowledgeValue.KNOWN_FALSE
    assert maintenance["health"].stale is KnowledgeValue.KNOWN_TRUE
    assert maintenance["backup"].stale is KnowledgeValue.KNOWN_FALSE


def test_unknown_stale_remains_unknown() -> None:
    result = query_knowledge(
        build_snapshot(),
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    assert isinstance(result.data, SystemStatusQueryData)
    brain = next(
        item
        for item in result.data.services
        if item.name == "brain"
    )
    assert brain.stale is KnowledgeValue.UNKNOWN
    assert brain.to_compact_dict()["stale"] == "unknown"


def test_provenance_is_preserved_and_aggregated() -> None:
    system = query_knowledge(
        build_snapshot(),
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    assert [source.value for source in system.sources] == [
        "core_runtime",
        "health_report",
    ]
    detail = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    assert [source.value for source in detail.sources] == [
        "core_runtime",
        "hardware_registry",
    ]


def test_schema_version_uses_canonical_constant() -> None:
    result = query_knowledge(
        build_snapshot(),
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    assert KNOWLEDGE_SCHEMA_VERSION == 1
    assert result.knowledge_schema_version == KNOWLEDGE_SCHEMA_VERSION
    assert result.to_compact_dict()["knowledge_schema_version"] == 1


def test_future_schema_fails_safe_before_selection() -> None:
    snapshot = build_snapshot()
    object.__setattr__(
        snapshot,
        "schema_version",
        KNOWLEDGE_SCHEMA_VERSION + 1,
    )
    result = query_knowledge(
        snapshot,
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    assert result.scope is KnowledgeQueryScope.UNSUPPORTED
    assert result.data is None
    assert result.incomplete is True
    assert (
        result.reason
        is KnowledgeQueryReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
    )
    assert result.knowledge_schema_version == 2


def test_query_does_not_mutate_snapshot() -> None:
    snapshot = build_snapshot()
    before = json.dumps(snapshot.to_compact_dict(), sort_keys=True)
    query_knowledge(snapshot, SYSTEM_DECISION, "ALEX có ổn không?")
    query_knowledge(snapshot, DEVICE_DECISION, "ESP01 online không?")
    after = json.dumps(snapshot.to_compact_dict(), sort_keys=True)
    assert after == before


def test_query_result_and_nested_data_are_immutable() -> None:
    result = query_knowledge(
        build_snapshot(),
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    with pytest.raises(FrozenInstanceError):
        result.incomplete = False  # type: ignore[misc]
    assert isinstance(result.data, DeviceDetailQueryData)
    assert result.data.device is not None
    with pytest.raises(FrozenInstanceError):
        result.data.device.online = KnowledgeValue.KNOWN_FALSE  # type: ignore[misc]
    assert isinstance(result.data.restricted_capabilities, tuple)


def test_query_result_is_strict_json_serializable() -> None:
    result = query_knowledge(
        build_snapshot(),
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    compact = compact_knowledge_query(result)
    encoded = json.dumps(compact, allow_nan=False)
    assert json.loads(encoded) == compact


def test_query_result_is_deterministic() -> None:
    snapshot = build_snapshot()
    left = query_knowledge(
        snapshot,
        DEVICE_DECISION,
        "ESP01 online không?",
    )
    right = query_knowledge(
        snapshot,
        DEVICE_DECISION,
        "esp01 online không?",
    )
    assert json.dumps(left.to_compact_dict()) == json.dumps(
        right.to_compact_dict()
    )


def test_secret_regression_does_not_leak_unselected_data() -> None:
    secret = "NEVER_QUERY_THIS_SECRET"
    snapshot = build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        services={
            "core": {
                "status": "online",
                "detail": f"Authorization: Bearer {secret}",
                "token": secret,
            }
        },
        devices={
            "esp01": {
                **device_input("esp01"),
                "password": secret,
                "capabilities": {
                    "relay_1": {
                        "verification_status": "restricted",
                        "state": secret,
                    }
                },
            }
        },
    )
    for decision, text in (
        (SYSTEM_DECISION, "ALEX có ổn không?"),
        (DEVICE_DECISION, "ESP01 online không?"),
    ):
        encoded = json.dumps(
            query_knowledge(
                snapshot,
                decision,
                text,
            ).to_compact_dict()
        )
        assert secret not in encoded
        assert "authorization" not in encoded.lower()
        assert "password" not in encoded.lower()


def test_hundred_device_system_query_has_no_device_dump() -> None:
    devices = {
        f"esp{index:03d}": device_input(f"esp{index:03d}")
        for index in range(100)
    }
    snapshot = build_snapshot(devices=devices)
    full_size = len(json.dumps(snapshot.to_compact_dict()))
    result = query_knowledge(
        snapshot,
        SYSTEM_DECISION,
        "ALEX có ổn không?",
    )
    compact = result.to_compact_dict()
    encoded = json.dumps(compact)
    assert "devices" not in compact["data"]
    assert len(encoded) < full_size // 10


def test_hundred_device_detail_contains_only_requested_device() -> None:
    devices = {
        f"esp{index:03d}": device_input(f"esp{index:03d}")
        for index in range(100)
    }
    result = query_knowledge(
        build_snapshot(devices=devices),
        DEVICE_DECISION,
        "ESP042 online không?",
    )
    encoded = json.dumps(result.to_compact_dict())
    assert '"esp042"' in encoded
    assert '"esp041"' not in encoded
    assert '"esp043"' not in encoded


def test_llm_route_returns_safe_unsupported_result() -> None:
    decision = route_intelligence("giải thích hệ thống này")
    result = query_knowledge(
        build_snapshot(),
        decision,
        "giải thích hệ thống này",
    )
    assert decision.route is IntelligenceRoute.LLM
    assert result.scope is KnowledgeQueryScope.UNSUPPORTED
    assert result.data is None
    assert result.reason is KnowledgeQueryReason.UNSUPPORTED_ROUTE


@pytest.mark.parametrize(
    "text,expected_route",
    [
        ("2 + 2", IntelligenceRoute.CALCULATOR),
        ("mấy giờ rồi?", IntelligenceRoute.TIME),
        ("thời tiết hôm nay?", IntelligenceRoute.WEATHER),
    ],
)
def test_non_system_routes_do_not_select_system_data(
    text: str,
    expected_route: IntelligenceRoute,
) -> None:
    decision = route_intelligence(text)
    result = query_knowledge(build_snapshot(), decision, text)
    assert decision.route is expected_route
    assert result.scope is KnowledgeQueryScope.UNSUPPORTED
    assert result.data is None


@pytest.mark.parametrize(
    "text",
    [
        "bật đèn test",
        "tắt đèn test",
        "đổi room mode",
        "chạy mission",
    ],
)
def test_mutation_text_never_creates_read_only_execution_path(
    text: str,
) -> None:
    decision = route_intelligence(text)
    result = query_knowledge(build_snapshot(), decision, text)
    assert decision.route is IntelligenceRoute.LLM
    assert decision.allowed_tool_names == ()
    assert result.scope is KnowledgeQueryScope.UNSUPPORTED
    assert result.data is None


def test_relay_mutation_does_not_call_or_bypass_safety_policy() -> None:
    text = "bật relay_1"
    decision = route_intelligence(text)
    with (
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
        result = query_knowledge(build_snapshot(), decision, text)
    assert decision.route is IntelligenceRoute.LLM
    assert result.scope is KnowledgeQueryScope.UNSUPPORTED
    assert result.data is None


def test_query_performs_no_network_mqtt_ollama_or_hardware_execution() -> None:
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("urllib.request.urlopen", side_effect=AssertionError("network")),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("hardware execution"),
        ),
    ):
        result = query_knowledge(
            build_snapshot(),
            DEVICE_DECISION,
            "ESP01 online không?",
        )
    assert result.scope is KnowledgeQueryScope.DEVICE_DETAIL


def test_one_thousand_queries_are_pure_local_selection() -> None:
    devices = {
        f"esp{index:03d}": device_input(f"esp{index:03d}")
        for index in range(100)
    }
    snapshot = build_snapshot(devices=devices)
    for index in range(1000):
        if index % 2:
            result = query_knowledge(
                snapshot,
                SYSTEM_DECISION,
                "ALEX có ổn không?",
            )
            assert result.scope is KnowledgeQueryScope.SYSTEM_STATUS
        else:
            result = query_knowledge(
                snapshot,
                DEVICE_DECISION,
                "ESP042 online không?",
            )
            assert result.scope is KnowledgeQueryScope.DEVICE_DETAIL
