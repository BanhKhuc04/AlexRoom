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
        route_observation_sink=Mock(),
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

    snapshot = router.metrics.snapshot()
    assert snapshot["total_requests"] == 10000
    assert snapshot["successes"] == 10000
    assert snapshot["failures"] == 0
    assert snapshot["brain_calls"] == 2500
    assert snapshot["deterministic_actions"] == 2500
    assert snapshot["restricted_refusals"] == 2500

    assert snapshot["route_counts"]["execute_action"] == 2500
    assert snapshot["route_counts"]["refuse_restricted"] == 2500
    assert snapshot["route_counts"]["respond_fast"] == 2500
    assert snapshot["route_counts"]["call_brain"] == 2500

    assert snapshot["min_duration_ms"] is not None
    assert snapshot["max_duration_ms"] is not None


def test_observability_sink_failure_does_not_affect_successful_route() -> None:
    # Setup similar to above, but route_observation_sink raises Exception
    mock_sink = Mock(side_effect=Exception("Audit failure"))

    mock_executor = Mock(return_value=CoreBrainChatResponse(
        request_id="sink-fail",
        assistant_text="fallback",
        proposed_tool_calls=[],
        tool_results=[],
        brain_called=True
    ))

    router = IntelligenceRouter(
        core_brain_integration=Mock(),
        fast_path_evaluator=Mock(return_value=None), # will fallback
        shadow_observer=Mock(),
        brain_request_builder=Mock(),
        brain_chat_executor=mock_executor,
        fast_path_enabled=lambda: True,
        action_fast_path_enabled=lambda: True,
        shadow_enabled=lambda: True,
        audit_logger=Mock(),
        route_observation_sink=mock_sink,
    )

    request = BrainChatRequest(request_id="sink-fail", user_text="hello")
    response = router.dispatch(request)

    assert response.assistant_text == "fallback"
    assert mock_sink.call_count == 1

    snapshot = router.metrics.snapshot()
    assert snapshot["total_requests"] == 1
    assert snapshot["successes"] == 1


def test_router_performance_regression() -> None:
    # Measure pure router overhead (no sleep, no I/O)
    mock_fast_path = Mock(return_value=None)
    mock_executor = Mock(return_value=CoreBrainChatResponse(
        request_id="perf",
        assistant_text="resp",
        proposed_tool_calls=[],
        tool_results=[],
    ))

    router = IntelligenceRouter(
        core_brain_integration=Mock(),
        fast_path_evaluator=mock_fast_path,
        shadow_observer=Mock(),
        brain_request_builder=Mock(),
        brain_chat_executor=mock_executor,
        fast_path_enabled=lambda: True,
        action_fast_path_enabled=lambda: True,
        shadow_enabled=lambda: True,
        audit_logger=Mock(),
        route_observation_sink=Mock(),
    )

    request = BrainChatRequest(request_id="perf", user_text="hello")

    import time
    start = time.monotonic()
    # 1000 iterations to measure baseline overhead
    for _ in range(1000):
        router.dispatch(request)
    end = time.monotonic()

    # 1000 iterations should be extremely fast (typically < 0.2s)
    # Give a generous upper bound for CI hardware
    assert end - start < 2.0


def test_route_observation_does_not_call_durable_audit() -> None:
    mock_audit = Mock()
    mock_sink = Mock()
    mock_executor = Mock(return_value=CoreBrainChatResponse(
        request_id="durable-test",
        assistant_text="resp",
        proposed_tool_calls=[],
        tool_results=[],
    ))

    router = IntelligenceRouter(
        core_brain_integration=Mock(),
        fast_path_evaluator=Mock(return_value=None),
        shadow_observer=Mock(),
        brain_request_builder=Mock(),
        brain_chat_executor=mock_executor,
        fast_path_enabled=lambda: True,
        action_fast_path_enabled=lambda: True,
        shadow_enabled=lambda: True,
        audit_logger=mock_audit,
        route_observation_sink=mock_sink,
    )

    request = BrainChatRequest(request_id="durable-test", user_text="test")
    router.dispatch(request)

    # Prove structured sink invoked exactly once
    assert mock_sink.call_count == 1

    # Prove normal durability logger was NEVER called for route_observation
    # It might be called for deterministic failure, but here it's CALL_BRAIN success
    assert mock_audit.call_count == 0

    # Prove metric incremented exactly once
    snapshot = router.metrics.snapshot()
    assert snapshot["total_requests"] == 1
