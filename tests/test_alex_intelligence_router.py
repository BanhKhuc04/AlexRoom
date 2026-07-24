import pytest
from unittest.mock import Mock, patch

from alex_brain_tools import BrainChatRequest
from alex_intelligence_router import IntelligenceRouter, RouterExecutionError
from alex_intelligence_runtime import IntelligenceRuntimeDecision, RuntimeOutcome
from alex_intelligence_fast_path import IntelligenceFastPathResult, FastPathStatus, FastPathReason
from alex_knowledge_query import KnowledgeQueryScope
from alex_brain_integration import CoreBrainChatResponse, BrainToolCall

def test_deterministic_ten_thousand_route_soak() -> None:
    # Set up mocks
    mock_core_brain = Mock()
    mock_core_brain.chat_deterministic.return_value = CoreBrainChatResponse(
        request_id="soak",
        assistant_text="[Deterministic Action Fast Path]",
        proposed_tool_calls=[],
        tool_results=[],
        route="deterministic_safe_action",
        brain_called=False
    )
    
    mock_fast_path_eval = Mock()
    mock_shadow_observer = Mock()
    mock_request_builder = Mock(return_value=BrainChatRequest(request_id="soak", user_text="hello"))
    mock_executor = Mock(return_value=CoreBrainChatResponse(
        request_id="soak",
        assistant_text="legacy",
        proposed_tool_calls=[],
        tool_results=[],
        brain_called=True
    ))

    router = IntelligenceRouter(
        core_brain_integration=mock_core_brain,
        fast_path_evaluator=mock_fast_path_eval,
        shadow_observer=mock_shadow_observer,
        brain_request_builder=mock_request_builder,
        brain_chat_executor=mock_executor,
        fast_path_enabled=lambda: True,
        action_fast_path_enabled=lambda: True,
        shadow_enabled=lambda: True,
        audit_logger=Mock(),
    )
    
    # 1. Action route
    action_decision = Mock(spec=IntelligenceRuntimeDecision)
    action_decision.outcome = RuntimeOutcome.EXECUTE_ACTION
    action_decision.response_text = None
    action_decision.action_selection = Mock()
    action_decision.action_selection.name = "set_test_led"
    action_decision.action_selection.deterministic_arguments = {"value": True}
    
    action_result = IntelligenceFastPathResult(
        enabled=True,
        status=FastPathStatus.HANDLED,
        reason=FastPathReason.INELIGIBLE_PLAN,
        outcome=RuntimeOutcome.EXECUTE_ACTION,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        brain_skipped=True,
        assistant_text=None,
        decision=action_decision
    )
    
    # 2. Refusal route
    refusal_decision = Mock(spec=IntelligenceRuntimeDecision)
    refusal_decision.outcome = RuntimeOutcome.REFUSE_RESTRICTED
    refusal_decision.response_text = "Refused"
    
    refusal_result = IntelligenceFastPathResult(
        enabled=True,
        status=FastPathStatus.HANDLED,
        reason=FastPathReason.INELIGIBLE_PLAN,
        outcome=RuntimeOutcome.REFUSE_RESTRICTED,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        brain_skipped=True,
        assistant_text=None,
        decision=refusal_decision
    )

    # 3. Fast response route
    fast_decision = Mock(spec=IntelligenceRuntimeDecision)
    fast_decision.outcome = RuntimeOutcome.RESPOND_FAST
    fast_decision.response_text = None
    
    fast_result = IntelligenceFastPathResult(
        enabled=True,
        status=FastPathStatus.HANDLED,
        reason=FastPathReason.READ_ONLY_RESPONSE,
        outcome=RuntimeOutcome.RESPOND_FAST,
        scope=KnowledgeQueryScope.SYSTEM_STATUS,
        brain_skipped=True,
        assistant_text="Fast response",
        decision=fast_decision
    )

    # 4. Fallback route
    fallback_result = None

    test_cases = [action_result, refusal_result, fast_result, fallback_result]
    
    request = BrainChatRequest(request_id="soak", user_text="soak")

    import time
    start = time.monotonic()
    
    for i in range(10000):
        # Rotate through scenarios
        case = test_cases[i % 4]
        mock_fast_path_eval.return_value = case
        
        response = router.dispatch(request)
        
        if i % 4 == 0:
            assert response.route == "deterministic_safe_action"
            assert mock_core_brain.chat_deterministic.call_count == (i // 4) + 1
        elif i % 4 == 1:
            assert response.route == "restricted_capability_refusal"
        elif i % 4 == 2:
            assert response.assistant_text == "Fast response"
        elif i % 4 == 3:
            assert response.assistant_text == "legacy"
            assert mock_executor.call_count == (i // 4) + 1
            
    end = time.monotonic()
    # It should easily pass within seconds
    assert end - start < 5.0
    
    # Verify shadow observer was called exactly 10,000 times
    assert mock_shadow_observer.call_count == 10000
