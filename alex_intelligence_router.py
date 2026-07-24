from __future__ import annotations

import logging
from collections.abc import Callable

from alex_brain_tools import BrainChatRequest
from alex_brain_integration import CoreBrainChatResponse, CoreBrainIntegration, BrainToolCall
from alex_intelligence_fast_path import IntelligenceFastPathResult
from alex_intelligence_runtime import RuntimeOutcome

_LOGGER = logging.getLogger("alex.intelligence.router")


class RouterExecutionError(RuntimeError):
    pass


class IntelligenceRouter:
    def __init__(
        self,
        core_brain_integration: CoreBrainIntegration,
        fast_path_evaluator: Callable[[BrainChatRequest], IntelligenceFastPathResult],
        shadow_observer: Callable[[BrainChatRequest, IntelligenceFastPathResult | None], None],
        brain_request_builder: Callable[[BrainChatRequest, IntelligenceFastPathResult | None], BrainChatRequest],
        brain_chat_executor: Callable[[BrainChatRequest], CoreBrainChatResponse],
        fast_path_enabled: Callable[[], bool],
        action_fast_path_enabled: Callable[[], bool],
        shadow_enabled: Callable[[], bool],
        audit_logger: Callable[[str, str, dict[str, Any]], None],
    ):
        self.core_brain_integration = core_brain_integration
        self.fast_path_evaluator = fast_path_evaluator
        self.shadow_observer = shadow_observer
        self.brain_request_builder = brain_request_builder
        self.brain_chat_executor = brain_chat_executor
        self.fast_path_enabled = fast_path_enabled
        self.action_fast_path_enabled = action_fast_path_enabled
        self.shadow_enabled = shadow_enabled
        self.audit_logger = audit_logger

    def dispatch(self, payload: BrainChatRequest) -> CoreBrainChatResponse:
        fast_path_result: IntelligenceFastPathResult | None = None
        
        is_fast_path = self.fast_path_enabled()
        is_action_fast_path = self.action_fast_path_enabled()
        is_shadow = self.shadow_enabled()
        
        if is_fast_path or is_action_fast_path:
            try:
                fast_path_result = self.fast_path_evaluator(payload)
            except Exception:
                pass
                
            if is_shadow:
                try:
                    self.shadow_observer(payload, fast_path_result)
                except Exception:
                    pass
                    
            if isinstance(fast_path_result, IntelligenceFastPathResult) and fast_path_result.decision:
                decision = fast_path_result.decision
                
                # Commit: FAST_RESPONSE
                if decision.outcome is RuntimeOutcome.RESPOND_FAST and fast_path_result.handled:
                    return CoreBrainChatResponse(
                        request_id=payload.request_id,
                        assistant_text=fast_path_result.assistant_text or "",
                        proposed_tool_calls=[],
                        tool_results=[],
                    )

                # Commit: RESTRICTED_REFUSAL
                if decision.outcome is RuntimeOutcome.REFUSE_RESTRICTED:
                    return CoreBrainChatResponse(
                        request_id=payload.request_id,
                        assistant_text=decision.response_text or "Hành động này bị giới hạn bởi hệ thống an toàn.",
                        proposed_tool_calls=[],
                        tool_results=[],
                        route="restricted_capability_refusal",
                        brain_called=False,
                    )

                # Commit: DETERMINISTIC_SAFE_ACTION
                if decision.outcome is RuntimeOutcome.EXECUTE_ACTION and decision.action_selection:
                    tool_call = BrainToolCall(
                        name=decision.action_selection.name,
                        arguments=decision.action_selection.deterministic_arguments or {},
                    )
                    try:
                        response = self.core_brain_integration.chat_deterministic(
                            request_id=payload.request_id,
                            user_text=payload.user_text,
                            tool_call=tool_call,
                            assistant_text="[Deterministic Action Fast Path]",
                        )
                        if any(result.status == "error" for result in response.tool_results):
                            raise RouterExecutionError("Tool execution failed")
                        return response
                    except RouterExecutionError:
                        raise
                    except Exception as error:
                        self.audit_logger(
                            "deterministic_execution_failed",
                            "warning",
                            {
                                "request_id": payload.request_id,
                                "route": "deterministic_safe_action",
                                "tool_name": tool_call.name,
                                "brain_called": False,
                            }
                        )
                        raise RouterExecutionError(f"Deterministic execution failed: {error}") from error
        
        elif is_shadow:
            try:
                self.shadow_observer(payload, None)
            except Exception:
                pass
                
        # Commit: CALL_BRAIN (explicit fallback)
        brain_request = self.brain_request_builder(payload, fast_path_result)
        return self.brain_chat_executor(brain_request)
