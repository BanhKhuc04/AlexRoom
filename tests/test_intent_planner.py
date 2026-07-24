from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from alex_intelligence import IntelligenceRoute, route_intelligence
from alex_intent_planner import (
    ClarificationReason,
    IntentCertainty,
    compact_intelligence_plan,
    plan_intelligence,
)
from alex_safety import CommandGateway, SafetyPolicy


def test_time_intent_is_one_exact_step_without_clarification() -> None:
    plan = plan_intelligence("Mấy giờ rồi?")
    assert len(plan.steps) == 1
    assert plan.steps[0].decision.route is IntelligenceRoute.TIME
    assert plan.steps[0].certainty is IntentCertainty.EXACT
    assert plan.steps[0].requires_clarification is False
    assert plan.multi_intent is False
    assert plan.requires_clarification is False


def test_system_status_reuses_router_tool_contract() -> None:
    plan = plan_intelligence(
        "Cho tôi xem trạng thái hệ thống ALEX"
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].decision.route is IntelligenceRoute.SYSTEM
    assert plan.steps[0].decision.allowed_tool_names == (
        "system_status",
    )
    assert plan.steps[0].certainty is IntentCertainty.EXACT


def test_exact_esp01_device_semantics_are_preserved() -> None:
    plan = plan_intelligence("ESP01 online không?")
    step = plan.steps[0]
    assert step.decision.route is IntelligenceRoute.SYSTEM
    assert step.decision.allowed_tool_names == ("list_devices",)
    assert step.certainty is IntentCertainty.EXACT
    assert step.normalized_text == "esp01 online khong"


def test_clear_explanation_is_exact_llm_without_clarification() -> None:
    plan = plan_intelligence(
        "giải thích tại sao hệ thống chậm"
    )
    step = plan.steps[0]
    assert step.decision.route is IntelligenceRoute.LLM
    assert step.certainty is IntentCertainty.EXACT
    assert step.requires_clarification is False
    assert plan.requires_clarification is False


def test_clear_story_request_is_not_mistaken_for_ambiguity() -> None:
    plan = plan_intelligence("kể cho tôi một câu chuyện")
    assert plan.steps[0].decision.route is IntelligenceRoute.LLM
    assert plan.steps[0].certainty is IntentCertainty.EXACT
    assert plan.requires_clarification is False


def test_generic_but_complete_llm_fallback_is_heuristic() -> None:
    plan = plan_intelligence(
        "hãy suy nghĩ về thiết kế căn phòng"
    )
    assert plan.steps[0].decision.route is IntelligenceRoute.LLM
    assert plan.steps[0].certainty is IntentCertainty.HEURISTIC
    assert plan.requires_clarification is False


def test_do_that_requires_clarification() -> None:
    plan = plan_intelligence("làm cái đó đi")
    step = plan.steps[0]
    assert step.certainty is IntentCertainty.UNKNOWN
    assert step.requires_clarification is True
    assert (
        step.clarification_reason
        is ClarificationReason.MISSING_TARGET
    )
    assert plan.requires_clarification is True
    assert plan.clarification_prompt == (
        "Bạn muốn ALEX thực hiện việc gì?"
    )


def test_turn_it_on_requires_specific_target_clarification() -> None:
    plan = plan_intelligence("bật nó lên")
    assert plan.steps[0].certainty is IntentCertainty.UNKNOWN
    assert plan.steps[0].requires_clarification is True
    assert plan.clarification_prompt == "Bạn muốn bật thiết bị nào?"


def test_check_that_requires_clarification() -> None:
    plan = plan_intelligence("kiểm tra cái đó")
    assert plan.steps[0].certainty is IntentCertainty.UNKNOWN
    assert plan.clarification_prompt == "Bạn muốn kiểm tra gì?"


def test_time_then_test_led_produces_two_ordered_steps() -> None:
    plan = plan_intelligence(
        "Mấy giờ rồi, bật đèn test luôn"
    )
    assert plan.multi_intent is True
    assert len(plan.steps) == 2
    assert [step.index for step in plan.steps] == [0, 1]
    assert [
        step.decision.route
        for step in plan.steps
    ] == [IntelligenceRoute.TIME, IntelligenceRoute.LLM]
    assert all(
        step.certainty is IntentCertainty.EXACT
        for step in plan.steps
    )
    assert plan.steps[1].decision.reason == (
        "guarded_mutation_command_falls_back"
    )


def test_system_status_then_device_list_preserves_order() -> None:
    plan = plan_intelligence(
        "trạng thái ALEX rồi liệt kê thiết bị"
    )
    assert len(plan.steps) == 2
    assert [
        step.decision.allowed_tool_names
        for step in plan.steps
    ] == [
        ("system_status",),
        ("list_devices",),
    ]
    assert [
        step.original_text
        for step in plan.steps
    ] == [
        "trạng thái ALEX",
        "liệt kê thiết bị",
    ]


def test_weather_then_time_preserves_order() -> None:
    plan = plan_intelligence(
        "thời tiết Hà Nội thế nào rồi mấy giờ rồi?"
    )
    assert [
        step.decision.route
        for step in plan.steps
    ] == [
        IntelligenceRoute.WEATHER,
        IntelligenceRoute.TIME,
    ]


def test_three_intent_order_is_preserved() -> None:
    plan = plan_intelligence(
        "mấy giờ rồi; thời tiết Hà Nội thế nào; bật đèn test"
    )
    assert plan.multi_intent is True
    assert [
        step.decision.route
        for step in plan.steps
    ] == [
        IntelligenceRoute.TIME,
        IntelligenceRoute.WEATHER,
        IntelligenceRoute.LLM,
    ]
    assert [step.index for step in plan.steps] == [0, 1, 2]


def test_empty_input_returns_zero_step_safe_clarification() -> None:
    plan = plan_intelligence("")
    assert plan.steps == ()
    assert plan.multi_intent is False
    assert plan.requires_clarification is True
    assert plan.clarification_prompt == "Bạn muốn ALEX làm gì?"


def test_whitespace_input_returns_zero_step_safe_clarification() -> None:
    plan = plan_intelligence("   \t ")
    assert plan.steps == ()
    assert plan.requires_clarification is True


def test_cpu_and_ram_is_not_split_into_unrelated_intents() -> None:
    plan = plan_intelligence("CPU và RAM hiện tại thế nào?")
    assert len(plan.steps) == 1
    assert plan.multi_intent is False
    assert plan.steps[0].original_text == (
        "CPU và RAM hiện tại thế nào"
    )


def test_two_weather_locations_are_not_split() -> None:
    plan = plan_intelligence(
        "thời tiết Hà Nội và Hải Phòng thế nào?"
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].decision.route is IntelligenceRoute.WEATHER


def test_and_splits_only_when_both_sides_are_complete_intents() -> None:
    plan = plan_intelligence(
        "thời tiết Hà Nội thế nào và mấy giờ rồi?"
    )
    assert [
        step.decision.route
        for step in plan.steps
    ] == [
        IntelligenceRoute.WEATHER,
        IntelligenceRoute.TIME,
    ]


@pytest.mark.parametrize(
    "text",
    [
        "bật đèn test",
        "tắt đèn test",
        "đổi room mode",
        "chạy mission",
    ],
)
def test_action_intents_remain_on_current_llm_path(
    text: str,
) -> None:
    plan = plan_intelligence(text)
    assert len(plan.steps) == 1
    assert plan.steps[0].decision.route is IntelligenceRoute.LLM
    assert plan.steps[0].decision.reason == (
        "guarded_mutation_command_falls_back"
    )
    assert plan.steps[0].certainty is IntentCertainty.EXACT
    assert plan.requires_clarification is False


def test_relay_intent_is_a_plan_not_execution() -> None:
    plan = plan_intelligence("bật relay_1")
    assert plan.steps[0].decision.route is IntelligenceRoute.LLM
    assert plan.steps[0].decision.allowed_tool_names == ()
    assert plan.steps[0].decision.reason == (
        "guarded_mutation_command_falls_back"
    )


def test_time_then_relay_is_two_steps_without_safety_bypass() -> None:
    text = "mấy giờ rồi rồi bật relay_1"
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
        plan = plan_intelligence(text)
    assert [
        step.decision.route
        for step in plan.steps
    ] == [IntelligenceRoute.TIME, IntelligenceRoute.LLM]
    assert plan.steps[1].decision.allowed_tool_names == ()


def test_ambiguous_device_choice_requires_clarification() -> None:
    plan = plan_intelligence("ESP01 hay ESP02?")
    step = plan.steps[0]
    assert step.certainty is IntentCertainty.UNKNOWN
    assert (
        step.clarification_reason
        is ClarificationReason.AMBIGUOUS_DEVICE_REFERENCE
    )
    assert plan.requires_clarification is True
    assert plan.clarification_prompt == (
        "Bạn muốn chọn thiết bị nào và thực hiện việc gì?"
    )


def test_device_id_is_never_fuzzy_rewritten() -> None:
    exact = plan_intelligence("ESP01 online không?")
    fuzzy = plan_intelligence("ESP1 online không?")
    assert exact.steps[0].normalized_text.startswith("esp01")
    assert fuzzy.steps[0].normalized_text.startswith("esp1 ")
    assert "esp01" not in fuzzy.steps[0].normalized_text
    assert fuzzy.steps[0].decision.allowed_tool_names == ()


def test_plan_and_steps_are_immutable() -> None:
    plan = plan_intelligence("mấy giờ rồi")
    with pytest.raises(FrozenInstanceError):
        plan.multi_intent = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.steps[0].index = 9  # type: ignore[misc]
    assert isinstance(plan.steps, tuple)


def test_plan_is_deterministic() -> None:
    text = "trạng thái ALEX rồi liệt kê thiết bị"
    left = plan_intelligence(text)
    right = plan_intelligence(text)
    assert json.dumps(left.to_compact_dict()) == json.dumps(
        right.to_compact_dict()
    )


def test_plan_compact_representation_is_json_serializable() -> None:
    plan = plan_intelligence(
        "mấy giờ rồi, bật đèn test luôn"
    )
    compact = compact_intelligence_plan(plan)
    encoded = json.dumps(compact, allow_nan=False)
    assert json.loads(encoded) == compact
    assert "confidence" not in encoded
    assert not any(
        isinstance(value, float)
        for value in compact.values()
    )


def test_planner_performs_no_network_mqtt_ollama_or_hardware_execution() -> None:
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("urllib.request.urlopen", side_effect=AssertionError("network")),
        patch.object(
            CommandGateway,
            "request",
            side_effect=AssertionError("hardware execution"),
        ),
    ):
        plan = plan_intelligence(
            "mấy giờ rồi, bật đèn test luôn"
        )
    assert len(plan.steps) == 2


@pytest.mark.parametrize(
    "text",
    [
        "Mấy giờ rồi?",
        "Cho tôi xem trạng thái hệ thống ALEX",
        "ESP01 online không?",
        "bật relay_1",
        "giải thích tại sao hệ thống chậm",
    ],
)
def test_each_single_step_preserves_existing_router_behavior(
    text: str,
) -> None:
    direct = route_intelligence(text)
    planned = plan_intelligence(text)
    assert len(planned.steps) == 1
    assert planned.steps[0].decision == direct
