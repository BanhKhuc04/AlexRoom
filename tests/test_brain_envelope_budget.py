from __future__ import annotations

import json
from test_relevant_context import build_snapshot

from alex_brain_context_envelope import build_guarded_brain_request
from alex_brain_tools import BrainChatRequest, brain_tool_schemas_for_provider
from alex_intent_planner import plan_intelligence
from alex_relevant_context import build_relevant_context
from brain_service.provider import SYSTEM_INSTRUCTION

def measure_envelope(text: str) -> dict[str, int]:
    plan = plan_intelligence(text)
    snapshot = build_snapshot()
    context = build_relevant_context(plan, snapshot)
    legacy = BrainChatRequest(request_id="req-test", user_text=text)
    guarded = build_guarded_brain_request(request=legacy, plan=plan, snapshot=snapshot)
    
    from brain_service.service import _system_instruction
    
    full_sys_inst = _system_instruction(guarded)
    
    if getattr(guarded, "mode", None) == "exact_mutation":
        from brain_service.provider import DEDICATED_MUTATION_INSTRUCTION
        sys_inst_len = len(DEDICATED_MUTATION_INSTRUCTION.encode('utf-8'))
        context_json = guarded.context.model_dump_json().replace("<", "\\u003c").replace(">", "\\u003e")
        wrapper_len = len(full_sys_inst.encode('utf-8')) - sys_inst_len - len(context_json.encode('utf-8'))
        context_len = len(context_json.encode('utf-8'))
    else:
        sys_inst_len = len(SYSTEM_INSTRUCTION.encode('utf-8'))
        if guarded.context:
            context_json = guarded.context.model_dump_json().replace("<", "\\u003c").replace(">", "\\u003e")
            wrapper_len = len(full_sys_inst.encode('utf-8')) - sys_inst_len - len(context_json.encode('utf-8'))
            context_len = len(context_json.encode('utf-8'))
        else:
            wrapper_len = 0
            context_len = 0
    
    if guarded.allowed_tools:
        schemas = brain_tool_schemas_for_provider(guarded.allowed_tools)
        schemas_json = json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))
        schema_len = len(schemas_json.encode('utf-8'))
    else:
        schema_len = 0
        
    user_text_len = len(text.encode('utf-8'))
    total = sys_inst_len + wrapper_len + context_len + schema_len + user_text_len
    
    return {
        "system": sys_inst_len,
        "wrapper": wrapper_len,
        "context": context_len,
        "schema": schema_len,
        "user": user_text_len,
        "total": total,
    }

def test_exact_mutation_budget_is_bounded_and_deterministic() -> None:
    budget = measure_envelope("Bật test_led của esp01")
    
    assert budget["total"] < 1300, "Exact mutation payload must remain bounded"
    
    assert budget["system"] == 390
    assert budget["wrapper"] == 41
    assert budget["context"] == 558
    assert budget["schema"] == 215
    assert budget["total"] == 1230

def test_general_reasoning_budget_is_minimal() -> None:
    budget = measure_envelope("REST API là gì")
    
    assert budget["total"] < 1250
    assert budget["context"] == 205
    assert budget["schema"] == 0

def test_device_detail_budget_is_bounded() -> None:
    budget = measure_envelope("ESP01 online không?")
    assert budget["total"] < 1800
    assert budget["context"] == 549
    assert budget["schema"] == 199

def test_relay_mutation_budget_is_bounded_and_restricted() -> None:
    budget = measure_envelope("Bật relay_1 của esp01")
    
    assert budget["total"] < 1650
    assert budget["context"] == 536
    assert budget["schema"] == 0
