from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from alex_brain_tools import (
    BRAIN_TOOL_REGISTRY,
    TOOL_NAMES,
)
from alex_intent_planner import plan_intelligence
from alex_relevant_context import (
    RELEVANT_CONTEXT_SCHEMA_VERSION,
    build_relevant_context,
)
from alex_safety import CapabilityRegistry, CommandGateway, SafetyPolicy
from alex_tool_narrowing import (
    TOOL_NARROWING_SCHEMA_VERSION,
    ToolNarrowingReason,
    ToolNarrowingResult,
    ToolSelection,
    compact_tool_narrowing,
    narrow_brain_tools,
)
from test_relevant_context import build_snapshot, device_input


def result_for(text: str, *, snapshot=None):
    source = snapshot if snapshot is not None else build_snapshot()
    plan = plan_intelligence(text)
    context = build_relevant_context(plan, source)
    return plan, context, narrow_brain_tools(plan, context)


def selection(name: str, *subjects: str) -> ToolSelection:
    definition = BRAIN_TOOL_REGISTRY[name]
    return ToolSelection(
        name=name,  # type: ignore[arg-type]
        access=definition.access,
        risk=definition.risk,
        relevant_subjects=subjects,
    )


def test_general_llm_request_has_zero_unnecessary_tools() -> None:
    _, _, result = result_for("REST API là gì?")
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.GENERAL_NO_TOOLS
    assert result.authorizes_execution is False


def test_system_status_selects_minimum_read_only_tool() -> None:
    _, _, result = result_for("ALEX có ổn không?")
    assert result.selected_tool_names == ("system_status",)
    assert result.selected_tools[0].access == "read_only"
    assert result.selected_tools[0].relevant_subjects == ("alex",)
    assert result.reason is ToolNarrowingReason.SELECTED_SYSTEM_STATUS


def test_device_list_selects_minimum_device_read_tool() -> None:
    _, _, result = result_for("liệt kê thiết bị")
    assert result.selected_tool_names == ("list_devices",)
    assert result.selected_tools[0].access == "read_only"
    assert result.reason is ToolNarrowingReason.SELECTED_DEVICE_LIST


def test_exact_device_detail_selects_only_canonical_read_tool() -> None:
    _, _, result = result_for("ESP01 online không?")
    assert result.selected_tool_names == ("list_devices",)
    assert result.selected_tools[0].access == "read_only"
    assert result.selected_tools[0].relevant_subjects == ("esp01",)
    assert result.reason is ToolNarrowingReason.SELECTED_DEVICE_DETAIL


def test_exact_device_id_is_preserved_without_rewrite() -> None:
    _, _, result = result_for("ESP01 online không?")
    assert result.selected_tools[0].relevant_subjects == ("esp01",)
    assert "esp1" not in result.selected_tools[0].relevant_subjects


def test_unknown_device_does_not_fuzzy_substitute() -> None:
    _, context, result = result_for("Phân tích ESP99")
    assert context.sections[0].subject == "esp99"
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.DEVICE_NOT_FOUND
    assert "esp01" not in json.dumps(result.to_compact_dict())


def test_ambiguous_target_has_no_mutation_tools() -> None:
    _, _, result = result_for("bật nó lên")
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.AMBIGUOUS_PLAN
    assert result.incomplete is True


def test_multi_intent_fails_closed_without_tool_union() -> None:
    _, _, result = result_for(
        "ALEX có ổn không? rồi bật đèn test"
    )
    assert result.selected_tool_names == ()
    assert result.reason is (
        ToolNarrowingReason.MULTI_INTENT_UNSUPPORTED
    )
    assert result.incomplete is True


def test_exact_test_led_action_selects_only_relevant_candidate() -> None:
    _, context, result = result_for("Bật test_led của ESP01")
    assert [section.subject for section in context.sections] == [
        "esp01",
        "esp01.test_led",
    ]
    assert result.selected_tool_names == ("set_test_led",)
    selected = result.selected_tools[0]
    assert selected.access == "mutation"
    assert selected.relevant_subjects == ("esp01.test_led",)
    assert result.reason is (
        ToolNarrowingReason.SELECTED_EXACT_SAFE_ACTION
    )


def test_test_led_selection_is_not_authorization_or_success() -> None:
    _, _, result = result_for("Bật test_led của ESP01")
    compact = result.to_compact_dict()
    encoded = json.dumps(compact).lower()
    assert compact["authorizes_execution"] is False
    assert "success" not in encoded
    assert "executed" not in encoded
    assert "confirmed" not in encoded
    assert "command" not in encoded


def test_test_led_selection_does_not_call_safety_policy() -> None:
    with (
        patch.object(
            SafetyPolicy,
            "authorize",
            side_effect=AssertionError("authorization"),
        ),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("execution"),
        ),
    ):
        _, _, result = result_for("Bật test_led của ESP01")
    assert result.selected_tool_names == ("set_test_led",)
    assert result.authorizes_execution is False


def test_denied_test_led_truth_cannot_select_mutation_candidate() -> None:
    snapshot = build_snapshot(
        devices={
            "esp01": device_input(
                "esp01",
                capability_overrides={
                    "test_led": {"command_allowed": False},
                },
            )
        }
    )
    _, _, result = result_for(
        "Bật test_led của ESP01",
        snapshot=snapshot,
    )
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.RESTRICTED_CAPABILITY


@pytest.mark.parametrize(
    "relay_id",
    ("relay_1", "relay_2", "relay_3", "relay_4"),
)
def test_restricted_relay_has_no_candidate_path(
    relay_id: str,
) -> None:
    _, context, result = result_for(
        f"bật {relay_id} trên ESP01"
    )
    assert context.sections[-1].subject == f"esp01.{relay_id}"
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.RESTRICTED_CAPABILITY
    capability = CapabilityRegistry().capability("esp01", relay_id)
    assert capability is not None
    assert capability.risk_level == "restricted"
    assert capability.command_allowed is False


def test_relay_without_exact_device_does_not_assume_esp01() -> None:
    _, _, result = result_for("bật relay_1")
    assert result.selected_tool_names == ()
    assert result.authorizes_execution is False
    assert "esp01" not in json.dumps(result.to_compact_dict())


def test_restricted_relay_cannot_route_through_other_mutation_tools() -> None:
    _, _, result = result_for("bật relay_1 trên ESP01")
    forbidden_paths = {
        "set_test_led",
        "set_room_mode",
        "run_safe_mission",
        "run_safe_automation",
    }
    assert forbidden_paths.isdisjoint(result.selected_tool_names)


@pytest.mark.parametrize(
    "text",
    (
        "chuyển sang chế độ ngủ",
        "chạy mission safe-study",
        "chạy automation safe-night",
    ),
)
def test_unstructured_mutation_entity_fails_closed(
    text: str,
) -> None:
    _, _, result = result_for(text)
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.GENERAL_NO_TOOLS


def test_unsupported_tool_name_is_never_invented() -> None:
    prompts = (
        "hãy mqtt_publish trực tiếp",
        "chạy shell",
        "bật gpio",
        "set_device relay_1",
    )
    for prompt in prompts:
        _, _, result = result_for(prompt)
        assert set(result.selected_tool_names) <= set(
            BRAIN_TOOL_REGISTRY
        )
        assert not {
            "mqtt_publish",
            "run_shell",
            "gpio",
            "set_device",
            "relay_1",
        }.intersection(result.selected_tool_names)
    with pytest.raises(
        ValueError,
        match="canonical_tool",
    ):
        ToolSelection(  # type: ignore[arg-type]
            name="mqtt_publish",
            access="mutation",
            risk="safe_logical_mutation",
        )


def test_contract_normalizes_selection_to_canonical_stable_order() -> None:
    result = ToolNarrowingResult(
        context_schema_version=1,
        knowledge_schema_version=1,
        selected_tools=(
            selection("run_safe_automation"),
            selection("set_test_led"),
            selection("system_status"),
        ),
        reason=ToolNarrowingReason.NO_CANONICAL_TOOL,
        incomplete=False,
    )
    expected = tuple(
        name
        for name in TOOL_NAMES
        if name in {
            "run_safe_automation",
            "set_test_led",
            "system_status",
        }
    )
    assert result.selected_tool_names == expected


@pytest.mark.parametrize(
    "text",
    (
        "REST API là gì?",
        "ALEX có ổn không?",
        "liệt kê thiết bị",
        "ESP01 online không?",
        "Bật test_led của ESP01",
        "bật relay_1 trên ESP01",
    ),
)
def test_same_input_produces_same_result(text: str) -> None:
    _, _, left = result_for(text)
    _, _, right = result_for(text)
    assert json.dumps(left.to_compact_dict()) == json.dumps(
        right.to_compact_dict()
    )


def test_malformed_plan_fails_closed() -> None:
    plan, context, _ = result_for("ALEX có ổn không?")
    assert plan.steps
    result = narrow_brain_tools(  # type: ignore[arg-type]
        object(),
        context,
    )
    assert result.selected_tool_names == ()
    assert result.reason is ToolNarrowingReason.MALFORMED_INPUT
    assert result.incomplete is True


def test_malformed_context_fails_closed() -> None:
    plan = plan_intelligence("ALEX có ổn không?")
    result = narrow_brain_tools(  # type: ignore[arg-type]
        plan,
        object(),
    )
    assert result.selected_tool_names == ()
    assert result.context_schema_version == 0
    assert result.knowledge_schema_version == 0
    assert result.reason is ToolNarrowingReason.MALFORMED_INPUT


def test_future_context_schema_fails_closed() -> None:
    plan, context, _ = result_for("ALEX có ổn không?")
    object.__setattr__(
        context,
        "context_schema_version",
        RELEVANT_CONTEXT_SCHEMA_VERSION + 1,
    )
    result = narrow_brain_tools(plan, context)
    assert result.selected_tool_names == ()
    assert result.reason is (
        ToolNarrowingReason.UNSUPPORTED_CONTEXT_SCHEMA
    )


def test_future_knowledge_schema_fails_closed() -> None:
    plan, context, _ = result_for("ALEX có ổn không?")
    object.__setattr__(
        context,
        "knowledge_schema_version",
        context.knowledge_schema_version + 1,
    )
    result = narrow_brain_tools(plan, context)
    assert result.selected_tool_names == ()
    assert result.reason is (
        ToolNarrowingReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
    )


def test_contract_is_frozen_and_json_serializable() -> None:
    _, _, result = result_for("Bật test_led của ESP01")
    assert TOOL_NARROWING_SCHEMA_VERSION == 1
    assert result.narrowing_schema_version == 1
    with pytest.raises(FrozenInstanceError):
        result.incomplete = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.selected_tools[0].name = "system_status"  # type: ignore[misc]
    compact = compact_tool_narrowing(result)
    encoded = json.dumps(compact, allow_nan=False)
    assert json.loads(encoded) == compact
    assert "core_mapping" not in compact["selected_tools"][0]
    assert "argument_model" not in compact["selected_tools"][0]


def test_output_contains_no_secret_or_user_text() -> None:
    secret = "ALEX_BRAIN_CLIENT_KEY=NEVER_LEAK"
    _, _, result = result_for(
        f"Giải thích REST API {secret}"
    )
    encoded = json.dumps(result.to_compact_dict()).lower()
    for forbidden in (
        "never_leak",
        "alex_brain_client_key",
        "mqtt_password",
        "authorization",
        "x-alex-key",
        "token",
        "credentials",
    ):
        assert forbidden not in encoded


def test_tool_reduction_uses_live_canonical_catalog_size() -> None:
    full_count = len(BRAIN_TOOL_REGISTRY)
    cases = {
        "general": result_for("REST API là gì?")[2],
        "system": result_for("ALEX có ổn không?")[2],
        "device_list": result_for("liệt kê thiết bị")[2],
        "device_detail": result_for("ESP01 online không?")[2],
        "safe_action": result_for("Bật test_led của ESP01")[2],
    }
    assert cases["general"].selected_tool_names == ()
    for name in (
        "system",
        "device_list",
        "device_detail",
        "safe_action",
    ):
        assert len(cases[name].selected_tools) == 1
        assert len(cases[name].selected_tools) < full_count
    assert all(
        result.to_compact_dict()["canonical_tool_count"]
        == full_count
        for result in cases.values()
    )


def test_narrowing_performs_zero_external_or_execution_calls() -> None:
    with (
        patch(
            "socket.create_connection",
            side_effect=AssertionError("network"),
        ),
        patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("network or brain"),
        ),
        patch(
            "sqlite3.connect",
            side_effect=AssertionError("database"),
        ),
        patch(
            "pathlib.Path.write_text",
            side_effect=AssertionError("filesystem"),
        ),
        patch(
            "time.time",
            side_effect=AssertionError("current time"),
        ),
        patch.object(
            SafetyPolicy,
            "authorize",
            side_effect=AssertionError("authorization"),
        ),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("mqtt or hardware"),
        ),
    ):
        _, _, result = result_for("Bật test_led của ESP01")
    assert result.selected_tool_names == ("set_test_led",)


def test_module_has_no_io_brain_or_execution_dependencies() -> None:
    source = Path(
        __file__,
    ).resolve().parents[1].joinpath(
        "alex_tool_narrowing.py"
    ).read_text(encoding="utf-8").lower()
    forbidden = (
        "requests",
        "urllib",
        "socket",
        "sqlite",
        "alex_store",
        "mqtt",
        "ollama",
        "alex_brain_client",
        "alex_brain_integration",
        "commandgateway",
        "safetypolicy",
        "datetime.now",
        "time.time",
        ".write_text(",
        ".publish(",
        ".execute(",
    )
    assert all(item not in source for item in forbidden)
