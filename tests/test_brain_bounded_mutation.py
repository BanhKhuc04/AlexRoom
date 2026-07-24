from __future__ import annotations

from test_relevant_context import build_snapshot

from alex_brain_context_envelope import build_guarded_brain_request
from alex_brain_tools import BrainChatRequest, BrainRelevantContext
from alex_intent_planner import plan_intelligence
from brain_service.provider import DEDICATED_MUTATION_INSTRUCTION
from brain_service.service import _system_instruction

def _request_mode(text: str) -> str | None:
    plan = plan_intelligence(text)
    snapshot = build_snapshot()
    legacy = BrainChatRequest(request_id="req-test", user_text=text)
    guarded = build_guarded_brain_request(request=legacy, plan=plan, snapshot=snapshot)
    return guarded.mode

def _get_system_instruction(text: str) -> str:
    plan = plan_intelligence(text)
    snapshot = build_snapshot()
    legacy = BrainChatRequest(request_id="req-test", user_text=text)
    guarded = build_guarded_brain_request(request=legacy, plan=plan, snapshot=snapshot)
    return _system_instruction(guarded)

def test_exact_test_led_activates_bounded_mutation() -> None:
    assert _request_mode("Bật test_led của esp01") == "exact_mutation"
    assert _request_mode("Tắt test_led của esp01") == "exact_mutation"

def test_instruction_formatting_for_exact_mutation() -> None:
    inst = _get_system_instruction("Bật test_led của esp01")
    assert DEDICATED_MUTATION_INSTRUCTION in inst
    assert "<alex_core_context>" in inst

def test_ambiguous_mutation_does_not_activate() -> None:
    assert _request_mode("Bật test_led") is None
    assert _request_mode("Bật test_led của thiết bị nào đó") is None

def test_unknown_node_does_not_activate() -> None:
    assert _request_mode("Bật test_led của esp99") is None

def test_unknown_capability_does_not_activate() -> None:
    assert _request_mode("Bật power_led của esp01") is None

def test_multiple_candidates_do_not_activate() -> None:
    assert _request_mode("Bật toàn bộ hệ thống") is None
    assert _request_mode("Bật đèn phòng khách và quạt") is None

def test_relay_does_not_activate() -> None:
    assert _request_mode("Bật relay_1 của esp01") is None
    assert _request_mode("Bật relay_2 của esp01") is None
    assert _request_mode("Bật relay_3 của esp01") is None
    assert _request_mode("Bật relay_4 của esp01") is None

def test_legacy_payload_serialization_excludes_mode() -> None:
    legacy = BrainChatRequest(request_id="req-test", user_text="Hello")
    dumped = legacy.model_dump(exclude_defaults=True)
    assert "mode" not in dumped, "mode must be omitted from legacy serialization"
    assert "context" not in dumped
    assert "allowed_tools" not in dumped

def test_exact_mutation_payload_serialization_includes_mode() -> None:
    plan = plan_intelligence("Bật test_led của esp01")
    snapshot = build_snapshot()
    legacy = BrainChatRequest(request_id="req-test", user_text="Bật test_led của esp01")
    guarded = build_guarded_brain_request(request=legacy, plan=plan, snapshot=snapshot)
    
    dumped = guarded.model_dump(exclude_none=True)
    assert "mode" in dumped
    assert dumped["mode"] == "exact_mutation"
