from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from alex_brain_client import BrainClientError
from alex_brain_integration import BrainToolCall, CoreBrainChatResponse, CoreBrainIntegration
from alex_brain_tools import BrainChatRequest
from alex_intelligence_fast_path import IntelligenceFastPathResult
from alex_intelligence_runtime import RuntimeOutcome

_LOGGER = logging.getLogger("alex.intelligence.router")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class IntelligenceRouteObservation:
    request_id: str
    route_outcome: str
    route_reason: str
    brain_called: bool
    deterministic: bool
    restricted: bool
    selected_tool: str | None
    started_at: str
    duration_ms: int
    brain_duration_ms: int | None
    execution_duration_ms: int | None
    success: bool
    error_code: str | None

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "route_outcome": self.route_outcome,
            "route_reason": self.route_reason,
            "brain_called": self.brain_called,
            "deterministic": self.deterministic,
            "restricted": self.restricted,
            "selected_tool": self.selected_tool,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "brain_duration_ms": self.brain_duration_ms,
            "execution_duration_ms": self.execution_duration_ms,
            "success": self.success,
            "error_code": self.error_code,
        }


class IntelligenceRouterMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_requests = 0
        self.successes = 0
        self.failures = 0
        self.brain_calls = 0
        self.deterministic_actions = 0
        self.restricted_refusals = 0
        self.route_counts: dict[str, int] = {}
        self.route_durations: dict[str, int] = {}
        self.min_duration_ms: int | None = None
        self.max_duration_ms: int | None = None

    def record(self, observation: IntelligenceRouteObservation) -> None:
        with self._lock:
            self.total_requests += 1
            if observation.success:
                self.successes += 1
            else:
                self.failures += 1

            if observation.brain_called:
                self.brain_calls += 1
            if observation.deterministic:
                self.deterministic_actions += 1
            if observation.restricted:
                self.restricted_refusals += 1

            self.route_counts[observation.route_outcome] = (
                self.route_counts.get(observation.route_outcome, 0) + 1
            )
            self.route_durations[observation.route_outcome] = (
                self.route_durations.get(observation.route_outcome, 0)
                + observation.duration_ms
            )

            if (
                self.min_duration_ms is None
                or observation.duration_ms < self.min_duration_ms
            ):
                self.min_duration_ms = observation.duration_ms
            if (
                self.max_duration_ms is None
                or observation.duration_ms > self.max_duration_ms
            ):
                self.max_duration_ms = observation.duration_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_requests": self.total_requests,
                "successes": self.successes,
                "failures": self.failures,
                "brain_calls": self.brain_calls,
                "deterministic_actions": self.deterministic_actions,
                "restricted_refusals": self.restricted_refusals,
                "route_counts": dict(self.route_counts),
                "route_durations": dict(self.route_durations),
                "min_duration_ms": self.min_duration_ms,
                "max_duration_ms": self.max_duration_ms,
            }


class RouterExecutionError(RuntimeError):
    pass


class _DispatchObservationState:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.route_outcome = "unknown"
        self.route_reason = "unknown"
        self.brain_called = False
        self.deterministic = False
        self.restricted = False
        self.selected_tool: str | None = None
        self.started_at = _utc_now_iso()
        self.t0 = time.monotonic()
        self.brain_duration_ms: int | None = None
        self.execution_duration_ms: int | None = None
        self.success = False
        self.error_code: str | None = None

    def build_observation(self) -> IntelligenceRouteObservation:
        t1 = time.monotonic()
        duration_ms = int((t1 - self.t0) * 1000)
        return IntelligenceRouteObservation(
            request_id=self.request_id,
            route_outcome=self.route_outcome,
            route_reason=self.route_reason,
            brain_called=self.brain_called,
            deterministic=self.deterministic,
            restricted=self.restricted,
            selected_tool=self.selected_tool,
            started_at=self.started_at,
            duration_ms=duration_ms,
            brain_duration_ms=self.brain_duration_ms,
            execution_duration_ms=self.execution_duration_ms,
            success=self.success,
            error_code=self.error_code,
        )


class IntelligenceRouter:
    def __init__(
        self,
        core_brain_integration: CoreBrainIntegration,
        fast_path_evaluator: Callable[[BrainChatRequest], IntelligenceFastPathResult],
        shadow_observer: Callable[
            [BrainChatRequest, IntelligenceFastPathResult | None], None
        ],
        brain_request_builder: Callable[
            [BrainChatRequest, IntelligenceFastPathResult | None], BrainChatRequest
        ],
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
        self.metrics = IntelligenceRouterMetrics()

    def dispatch(self, payload: BrainChatRequest) -> CoreBrainChatResponse:
        obs_state = _DispatchObservationState(payload.request_id)
        try:
            response = self._execute_dispatch(payload, obs_state)
            obs_state.success = True
            return response
        except BrainClientError as error:
            obs_state.route_outcome = RuntimeOutcome.CALL_BRAIN.value
            obs_state.brain_called = True
            obs_state.success = False
            if error.code in {"brain_timeout", "brain_unavailable", "invalid_brain_response"}:
                obs_state.error_code = error.code
            else:
                obs_state.error_code = "brain_client_error"
            raise
        except RouterExecutionError:
            obs_state.route_outcome = RuntimeOutcome.EXECUTE_ACTION.value
            obs_state.route_reason = "deterministic_execution_failed"
            obs_state.deterministic = True
            obs_state.success = False
            obs_state.error_code = "deterministic_execution_failed"
            raise
        except Exception as error:
            obs_state.success = False
            obs_state.error_code = "router_evaluation_failed"
            raise
        finally:
            self._finalize_observation(obs_state)

    def _finalize_observation(self, obs_state: _DispatchObservationState) -> None:
        try:
            observation = obs_state.build_observation()
            self.metrics.record(observation)

            # Route observations are best-effort and must not affect authoritative execution.
	    # Persistence policy is delegated to the injected audit sink.
            self.audit_logger(
                "route_observation",
                "info",
                observation.to_compact_dict()
            )
        except Exception:
            pass

    def _execute_dispatch(
        self,
        payload: BrainChatRequest,
        obs_state: _DispatchObservationState,
    ) -> CoreBrainChatResponse:
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
                    obs_state.route_outcome = RuntimeOutcome.RESPOND_FAST.value
                    obs_state.route_reason = "fast_response_handled"
                    return CoreBrainChatResponse(
                        request_id=payload.request_id,
                        assistant_text=fast_path_result.assistant_text or "",
                        proposed_tool_calls=[],
                        tool_results=[],
                    )

                # Commit: RESTRICTED_REFUSAL
                if decision.outcome is RuntimeOutcome.REFUSE_RESTRICTED:
                    obs_state.route_outcome = RuntimeOutcome.REFUSE_RESTRICTED.value
                    obs_state.route_reason = "restricted_capability_refusal"
                    obs_state.restricted = True
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
                    obs_state.route_outcome = RuntimeOutcome.EXECUTE_ACTION.value
                    obs_state.route_reason = "deterministic_safe_action"
                    obs_state.deterministic = True
                    obs_state.selected_tool = decision.action_selection.name

                    tool_call = BrainToolCall(
                        name=decision.action_selection.name,
                        arguments=decision.action_selection.deterministic_arguments or {},
                    )

                    t0_exec = time.monotonic()
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
                        # Log the detailed error without exposing to the user
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
                    finally:
                        t1_exec = time.monotonic()
                        obs_state.execution_duration_ms = int((t1_exec - t0_exec) * 1000)

        elif is_shadow:
            try:
                self.shadow_observer(payload, None)
            except Exception:
                pass

        # Commit: explicit CALL_BRAIN route
        obs_state.route_outcome = RuntimeOutcome.CALL_BRAIN.value
        obs_state.route_reason = "brain_request_allowed"
        obs_state.brain_called = True

        brain_request = self.brain_request_builder(payload, fast_path_result)

        t0_brain = time.monotonic()
        try:
            return self.brain_chat_executor(brain_request)
        finally:
            t1_brain = time.monotonic()
            obs_state.brain_duration_ms = int((t1_brain - t0_brain) * 1000)
