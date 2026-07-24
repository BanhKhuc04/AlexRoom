from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from alex_intent_planner import plan_intelligence
from alex_knowledge import build_system_knowledge_snapshot
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeValue,
)
from alex_relevant_context import (
    RELEVANT_CONTEXT_SCHEMA_VERSION,
    RelevantContext,
    RelevantFact,
    RelevantContextReason,
    RelevantContextScope,
    RelevantContextSectionKind,
    build_relevant_context,
    compact_relevant_context,
)
from alex_safety import CapabilityRegistry, CommandGateway, SafetyPolicy


CAPTURED_AT = "2026-07-24T12:00:00+00:00"
OBSERVED_AT = "2026-07-24T11:59:00+00:00"


def device_input(
    device_id: str,
    *,
    online: object = True,
    observed_at: str | None = OBSERVED_AT,
    capability_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    registry = CapabilityRegistry().public_snapshot()["esp01"]
    capabilities = {
        key: dict(value)
        for key, value in registry["capabilities"].items()
    }
    if capability_overrides:
        for key, value in capability_overrides.items():
            if isinstance(value, dict) and key in capabilities:
                capabilities[key].update(value)
            else:
                capabilities[key] = value
    result: dict[str, object] = {
        **registry,
        "node_id": device_id,
        "online": online,
        "connection": (
            "online"
            if online is True
            else "offline" if online is False else "unknown"
        ),
        "capabilities": capabilities,
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
    services: object = None,
    health_stale: object = False,
):
    return build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        overall_status="healthy",
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
        services=(
            {
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
                "mqtt": {
                    "status": "online",
                    "source": "core_runtime",
                },
                "unrelated": {
                    "status": "warning",
                    "source": "core_runtime",
                },
            }
            if services is None
            else services
        ),
        devices=(
            {
                "esp01": device_input("esp01"),
                "esp02": device_input("esp02", online=False),
            }
            if devices is None
            else devices
        ),
        runtime={
            "room_mode": "home",
            "simulator": False,
            "observed_at": OBSERVED_AT,
            "source": "core_runtime",
        },
    )


def context_for(text: str, *, snapshot=None):
    source = snapshot if snapshot is not None else build_snapshot()
    return build_relevant_context(
        plan_intelligence(text),
        source,
    )


def compact_for(text: str, *, snapshot=None) -> dict[str, object]:
    return context_for(text, snapshot=snapshot).to_compact_dict()


def section_by_subject(context, subject: str):
    return next(
        section
        for section in context.sections
        if section.subject == subject
    )


def facts(section) -> dict[str, object]:
    return {
        fact.name: fact.value
        for fact in section.facts
    }


def large_snapshot(count: int = 100):
    return build_snapshot(
        devices={
            f"esp{index:03d}": device_input(
                f"esp{index:03d}",
                online=index % 2 == 0,
            )
            for index in range(count)
        }
    )


def encoded_size(document: dict[str, object]) -> int:
    return len(
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def test_system_status_selects_only_relevant_system_context() -> None:
    context = context_for("ALEX có ổn không?")
    assert context.scope is RelevantContextScope.SYSTEM_STATUS
    assert context.reason is RelevantContextReason.SELECTED_SYSTEM_STATUS
    assert [
        (section.kind, section.subject)
        for section in context.sections
    ] == [
        (RelevantContextSectionKind.SYSTEM, "alex"),
        (RelevantContextSectionKind.SERVICE, "brain"),
        (RelevantContextSectionKind.SERVICE, "core"),
        (RelevantContextSectionKind.MAINTENANCE, "backup"),
        (RelevantContextSectionKind.MAINTENANCE, "health"),
    ]
    encoded = json.dumps(context.to_compact_dict())
    for forbidden in (
        "devices",
        "capability",
        "relay_1",
        "esp01",
        "room_mode",
        "unrelated",
    ):
        assert forbidden not in encoded


def test_device_list_is_a_compact_inventory_without_capabilities() -> None:
    context = context_for("liệt kê thiết bị")
    assert context.scope is RelevantContextScope.DEVICE_LIST
    assert [section.subject for section in context.sections] == [
        "esp01",
        "esp02",
    ]
    assert all(
        section.kind is RelevantContextSectionKind.DEVICE
        for section in context.sections
    )
    encoded = json.dumps(context.to_compact_dict())
    assert "capability" not in encoded
    assert "relay_1" not in encoded
    assert "test_led" not in encoded


def test_device_detail_exact_esp01_contains_esp01_only() -> None:
    context = context_for("ESP01 online không?")
    assert context.scope is RelevantContextScope.DEVICE_DETAIL
    assert context.reason is RelevantContextReason.SELECTED_DEVICE_DETAIL
    assert [section.subject for section in context.sections] == ["esp01"]
    assert "esp02" not in json.dumps(context.to_compact_dict())


def test_unknown_device_does_not_substitute_another_device() -> None:
    context = context_for("Phân tích ESP99")
    assert context.scope is RelevantContextScope.DEVICE_DETAIL
    assert context.reason is RelevantContextReason.DEVICE_NOT_FOUND
    assert context.incomplete is True
    assert [section.subject for section in context.sections] == ["esp99"]
    assert facts(context.sections[0]) == {
        "found": False,
        "known": "unknown",
    }
    encoded = json.dumps(context.to_compact_dict())
    assert "esp01" not in encoded
    assert "esp02" not in encoded


@pytest.mark.parametrize(
    "relay_id",
    ("relay_1", "relay_2", "relay_3", "relay_4"),
)
def test_relay_restriction_truth_is_preserved_when_explicitly_relevant(
    relay_id: str,
) -> None:
    context = context_for(f"bật {relay_id} trên ESP01")
    assert context.scope is RelevantContextScope.DEVICE_DETAIL
    capability = section_by_subject(context, f"esp01.{relay_id}")
    capability_facts = facts(capability)
    assert capability.kind is RelevantContextSectionKind.CAPABILITY
    assert capability_facts["availability"] == "restricted"
    assert capability_facts["command_allowed"] is False
    assert capability_facts["hardware_verified"] is False
    assert "state" not in capability_facts
    encoded = json.dumps(context.to_compact_dict())
    assert '"restricted"' in encoded
    assert '"OFF"' not in encoded


def test_test_led_allowed_truth_is_preserved_when_explicitly_relevant() -> None:
    context = context_for("Phân tích ESP01 test_led")
    led = section_by_subject(context, "esp01.test_led")
    led_facts = facts(led)
    assert led_facts["availability"] is True
    assert led_facts["command_allowed"] is True
    assert led_facts["verification_status"] == (
        "basic_physical_validated"
    )
    assert led_facts["state"] is True


def test_general_llm_request_receives_no_system_dump() -> None:
    context = context_for("Giải thích REST API là gì")
    assert context.scope is RelevantContextScope.GENERAL
    assert context.reason is RelevantContextReason.NO_RELEVANT_KNOWLEDGE
    assert context.sections == ()
    assert context.sources == ()
    encoded = json.dumps(context.to_compact_dict())
    assert "esp01" not in encoded
    assert "core_runtime" not in encoded


def test_ambiguous_request_does_not_fabricate_target() -> None:
    context = context_for("bật nó lên")
    assert context.scope is RelevantContextScope.UNSUPPORTED
    assert context.reason is RelevantContextReason.AMBIGUOUS_PLAN
    assert context.incomplete is True
    assert context.sections == ()


def test_ambiguous_device_choice_does_not_select_either_device() -> None:
    context = context_for("ESP01 hay ESP02?")
    assert context.scope is RelevantContextScope.UNSUPPORTED
    assert context.sections == ()
    encoded = json.dumps(context.to_compact_dict())
    assert "esp01" not in encoded
    assert "esp02" not in encoded


def test_unknown_semantic_remains_unknown() -> None:
    snapshot = build_snapshot(
        devices={
            "esp01": device_input(
                "esp01",
                online="unknown",
            )
        }
    )
    device = section_by_subject(
        context_for("ESP01 online không?", snapshot=snapshot),
        "esp01",
    )
    assert facts(device)["online"] == "unknown"


def test_unavailable_semantic_remains_unavailable() -> None:
    snapshot = build_snapshot(
        devices={
            "esp01": device_input(
                "esp01",
                online="unavailable",
            )
        }
    )
    device = section_by_subject(
        context_for("ESP01 online không?", snapshot=snapshot),
        "esp01",
    )
    assert facts(device)["online"] == "unavailable"


def test_stale_and_unknown_freshness_are_preserved() -> None:
    context = context_for(
        "ALEX có ổn không?",
        snapshot=build_snapshot(health_stale=True),
    )
    health = section_by_subject(context, "health")
    brain = section_by_subject(context, "brain")
    assert health.stale is KnowledgeValue.KNOWN_TRUE
    assert health.to_compact_dict()["freshness"]["stale"] is True
    assert brain.stale is KnowledgeValue.UNKNOWN
    assert brain.to_compact_dict()["freshness"]["stale"] == "unknown"


def test_provenance_is_preserved_per_section_and_aggregated() -> None:
    system = context_for("ALEX có ổn không?")
    core = section_by_subject(system, "core")
    health = section_by_subject(system, "health")
    assert core.sources == (KnowledgeSource.CORE_RUNTIME,)
    assert health.sources == (KnowledgeSource.HEALTH_REPORT,)
    assert system.sources == (
        KnowledgeSource.CORE_RUNTIME,
        KnowledgeSource.HEALTH_REPORT,
    )

    device = context_for("ESP01 online không?")
    esp01 = section_by_subject(device, "esp01")
    assert esp01.sources == (
        KnowledgeSource.CORE_RUNTIME,
        KnowledgeSource.HARDWARE_REGISTRY,
    )


def test_observed_at_is_preserved_but_never_fabricated() -> None:
    observed = section_by_subject(
        context_for("ESP01 online không?"),
        "esp01",
    )
    assert observed.observed_at == OBSERVED_AT

    snapshot = build_snapshot(
        devices={
            "esp01": device_input(
                "esp01",
                observed_at=None,
            )
        },
        services={
            "core": {"status": "online"},
            "brain": {"status": "unknown"},
        },
    )
    context = context_for("ESP01 online không?", snapshot=snapshot)
    device = section_by_subject(context, "esp01")
    compact = device.to_compact_dict()
    assert device.observed_at is None
    assert "observed_at" not in compact["freshness"]
    assert context.snapshot_captured_at == CAPTURED_AT


def test_secret_like_fields_and_values_do_not_leak() -> None:
    secret = "NEVER_LEAK_THIS_VALUE"
    snapshot = build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        services={
            "core": {
                "status": "online",
                "ALEX_API_KEY": secret,
                "Authorization": f"Bearer {secret}",
                "detail": f"token={secret}",
            }
        },
        devices={
            "esp01": {
                **device_input(
                    "esp01",
                    capability_overrides={
                        "test_led": {
                            "state": f"ALEX_BRAIN_CLIENT_KEY={secret}",
                        }
                    },
                ),
                "password": secret,
                "X-ALEX-Key": secret,
                "X-ALEX-Brain-Key": secret,
                "mqtt_token": secret,
            }
        },
    )
    contexts = (
        context_for("ALEX có ổn không?", snapshot=snapshot),
        context_for("Phân tích ESP01 test_led", snapshot=snapshot),
    )
    encoded = json.dumps(
        [item.to_compact_dict() for item in contexts],
        ensure_ascii=False,
    ).lower()
    assert secret.lower() not in encoded
    for forbidden in (
        "alex_api_key",
        "alex_brain_client_key",
        "password",
        "token",
        "secret",
        "authorization",
        "x-alex-key",
        "x-alex-brain-key",
    ):
        assert forbidden not in encoded


def test_same_input_produces_stable_serialization_and_order() -> None:
    snapshot = build_snapshot(
        devices={
            "esp02": device_input("esp02"),
            "esp01": device_input("esp01"),
        }
    )
    left = compact_for("liệt kê thiết bị", snapshot=snapshot)
    right = compact_for("liệt kê thiết bị", snapshot=snapshot)
    assert json.dumps(left, ensure_ascii=False) == json.dumps(
        right,
        ensure_ascii=False,
    )
    assert [
        section["subject"]
        for section in left["sections"]
    ] == ["esp01", "esp02"]


def test_hundred_device_detail_contains_only_requested_device() -> None:
    snapshot = large_snapshot()
    context = context_for(
        "ESP042 online không?",
        snapshot=snapshot,
    )
    encoded = json.dumps(context.to_compact_dict())
    assert [section.subject for section in context.sections] == ["esp042"]
    assert '"esp042"' in encoded
    for unrelated in ("esp000", "esp041", "esp043", "esp099"):
        assert unrelated not in encoded


def test_hundred_device_contexts_are_structurally_smaller_than_snapshot() -> None:
    snapshot = large_snapshot()
    full_size = encoded_size(snapshot.to_compact_dict())
    system_size = encoded_size(
        compact_for("ALEX có ổn không?", snapshot=snapshot)
    )
    list_size = encoded_size(
        compact_for("liệt kê thiết bị", snapshot=snapshot)
    )
    detail_size = encoded_size(
        compact_for("ESP042 online không?", snapshot=snapshot)
    )
    assert system_size < full_size // 10
    assert list_size < full_size
    assert detail_size < full_size // 20


def test_contract_is_immutable_versioned_and_json_serializable() -> None:
    context = context_for("ALEX có ổn không?")
    assert RELEVANT_CONTEXT_SCHEMA_VERSION == 1
    assert context.context_schema_version == 1
    assert context.knowledge_schema_version == KNOWLEDGE_SCHEMA_VERSION
    assert isinstance(context.sections, tuple)
    with pytest.raises(FrozenInstanceError):
        context.incomplete = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.sections[0].subject = "other"  # type: ignore[misc]
    compact = compact_relevant_context(context)
    encoded = json.dumps(compact, allow_nan=False)
    assert json.loads(encoded) == compact


def test_contract_normalizes_collections_and_rejects_non_json_facts() -> None:
    context = RelevantContext(
        knowledge_schema_version=1,
        snapshot_captured_at=CAPTURED_AT,
        scope=RelevantContextScope.GENERAL,
        reason=RelevantContextReason.NO_RELEVANT_KNOWLEDGE,
        incomplete=False,
        sources=[],  # type: ignore[arg-type]
        sections=[],  # type: ignore[arg-type]
    )
    assert context.sources == ()
    assert context.sections == ()
    with pytest.raises(
        TypeError,
        match="fact_value_must_be_json_scalar",
    ):
        RelevantFact("bad", ["not", "scalar"])  # type: ignore[arg-type]


def test_future_knowledge_schema_fails_closed() -> None:
    snapshot = build_snapshot()
    object.__setattr__(
        snapshot,
        "schema_version",
        KNOWLEDGE_SCHEMA_VERSION + 1,
    )
    context = context_for("ALEX có ổn không?", snapshot=snapshot)
    assert context.scope is RelevantContextScope.UNSUPPORTED
    assert context.reason is (
        RelevantContextReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
    )
    assert context.knowledge_schema_version == 2
    assert context.sections == ()


@pytest.mark.parametrize(
    "plan",
    (object(), None, "not-a-plan"),
)
def test_malformed_plan_fails_safe_without_fabricated_context(
    plan: object,
) -> None:
    context = build_relevant_context(  # type: ignore[arg-type]
        plan,
        build_snapshot(),
    )
    assert context.scope is RelevantContextScope.UNSUPPORTED
    assert context.reason is RelevantContextReason.UNSUPPORTED_PLAN
    assert context.sections == ()


def test_malformed_snapshot_fails_safe() -> None:
    context = build_relevant_context(  # type: ignore[arg-type]
        plan_intelligence("ALEX có ổn không?"),
        object(),
    )
    assert context.scope is RelevantContextScope.UNSUPPORTED
    assert context.knowledge_schema_version == 0
    assert context.snapshot_captured_at == ""
    assert context.sections == ()


def test_exact_capability_matching_does_not_fuzzy_select() -> None:
    context = context_for("Phân tích ESP01 relay_1x")
    assert [section.subject for section in context.sections] == ["esp01"]
    assert "esp01.relay_1" not in json.dumps(context.to_compact_dict())


def test_action_context_is_factual_only_and_does_not_authorize() -> None:
    with (
        patch.object(
            SafetyPolicy,
            "authorize",
            side_effect=AssertionError("authorization"),
        ),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("hardware"),
        ),
    ):
        context = context_for("bật relay_1 trên ESP01")
    compact = context.to_compact_dict()
    assert compact["scope"] == "device_detail"
    assert "success" not in json.dumps(compact).lower()
    assert "authorized" not in json.dumps(compact).lower()


def test_builder_performs_zero_io_hardware_or_current_time_calls() -> None:
    with (
        patch(
            "socket.create_connection",
            side_effect=AssertionError("network"),
        ),
        patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("network"),
        ),
        patch(
            "sqlite3.connect",
            side_effect=AssertionError("database"),
        ),
        patch(
            "pathlib.Path.write_text",
            side_effect=AssertionError("filesystem write"),
        ),
        patch(
            "time.time",
            side_effect=AssertionError("current time"),
        ),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("hardware or mqtt"),
        ),
    ):
        context = context_for("bật relay_1 trên ESP01")
    assert context.scope is RelevantContextScope.DEVICE_DETAIL


def test_builder_module_has_no_external_io_or_execution_dependencies() -> None:
    source = Path(
        __file__,
    ).resolve().parents[1].joinpath(
        "alex_relevant_context.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "urllib",
        "socket",
        "sqlite",
        "alex_store",
        "mqtt",
        "ollama",
        "commandgateway",
        "safetypolicy",
        "datetime.now",
        "time.time",
        ".write_text(",
        ".publish(",
    )
    normalized = source.lower()
    assert all(item not in normalized for item in forbidden)
