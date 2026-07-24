from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal, Protocol

from pydantic import Field, ValidationError, model_validator

from alex_brain_client import BrainClientError
from alex_brain_mutations import (
    SET_TEST_LED_CORE_MAPPING,
    MutationOutcome,
)
from alex_brain_orchestration_boundary import (
    StoredOrchestrationExecutor,
    execute_stored_orchestration,
)
from alex_brain_room_mode import (
    RoomModeExecutor,
    execute_room_mode_proposal,
)
from alex_brain_reads import execute_authoritative_read
from alex_brain_tools import (
    BOUNDED_ID_PATTERN,
    MAX_REQUEST_ID_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_TOOL_CALLS,
    BrainChatRequest,
    BrainChatResponse,
    BrainToolCall,
    StrictContractModel,
    ToolName,
)


C4_EXECUTION_ALLOWLIST: Final[tuple[ToolName, ...]] = (
    "system_status",
    "list_devices",
)
C5_EXECUTION_ALLOWLIST: Final[tuple[ToolName, ...]] = (
    "system_status",
    "list_devices",
    "set_test_led",
)
C6A_EXECUTION_ALLOWLIST: Final[tuple[ToolName, ...]] = (
    "system_status",
    "list_devices",
    "set_test_led",
    "run_safe_mission",
)
C6B_EXECUTION_ALLOWLIST: Final[tuple[ToolName, ...]] = (
    *C6A_EXECUTION_ALLOWLIST,
    "run_safe_automation",
)
C7_EXECUTION_ALLOWLIST: Final[tuple[ToolName, ...]] = (
    "system_status",
    "list_devices",
    "set_test_led",
    "set_room_mode",
    "run_safe_mission",
    "run_safe_automation",
)
CoreToolResultStatus = Literal[
    "ok",
    "rejected",
    "error",
    "pending",
    "running",
    "confirmed",
    "completed",
    "failed",
]
CoreToolResultReason = Literal[
    "tool_not_enabled_in_c4",
    "batch_rejected_in_c4",
    "tool_not_enabled_in_c5",
    "batch_rejected_in_c5",
    "tool_not_enabled_in_c6a",
    "batch_rejected_in_c6a",
    "tool_not_enabled_in_c6b",
    "batch_rejected_in_c6b",
    "tool_not_allowed_by_request",
    "batch_rejected_by_request",
    "authoritative_read_failed",
    "safety_gateway_denied",
    "device_unavailable",
    "command_in_progress",
    "command_not_created",
    "command_lifecycle_failed",
    "mutation_execution_failed",
    "mission_not_found",
    "mission_not_brain_allowed",
    "mission_disabled",
    "mission_preflight_failed",
    "mission_execution_failed",
    "automation_not_found",
    "automation_not_brain_allowed",
    "automation_disabled",
    "automation_preflight_failed",
    "automation_execution_failed",
    "room_mode_execution_failed",
]


class CoreBrainToolResult(StrictContractModel):
    name: ToolName
    status: CoreToolResultStatus
    result: dict[str, object] | None = None
    reason: CoreToolResultReason | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "CoreBrainToolResult":
        if self.status in {
            "ok",
            "pending",
            "running",
            "confirmed",
            "completed",
        }:
            if self.result is None or self.reason is not None:
                raise ValueError(
                    "successful/read-pending result requires result and forbids reason"
                )
        elif self.status == "failed":
            if self.result is None or self.reason is None:
                raise ValueError("failed tool result requires result and reason")
        elif self.reason is None:
            raise ValueError("rejected/error tool result requires reason")
        return self


class CoreBrainChatResponse(StrictContractModel):
    request_id: str = Field(
        min_length=1,
        max_length=MAX_REQUEST_ID_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )
    assistant_text: str = Field(max_length=MAX_TEXT_LENGTH)
    proposed_tool_calls: list[BrainToolCall] = Field(
        default_factory=list,
        max_length=MAX_TOOL_CALLS,
    )
    tool_results: list[CoreBrainToolResult] = Field(
        default_factory=list,
        max_length=MAX_TOOL_CALLS,
    )


class BrainProposalClient(Protocol):
    def chat(self, request: BrainChatRequest) -> BrainChatResponse: ...


AuditWriter = Callable[[str, str, dict[str, object]], None]
ReadOperation = Callable[[], dict[str, object]]


class SetTestLedExecutor(Protocol):
    def execute(self, value: bool) -> MutationOutcome: ...


class CoreBrainIntegration:
    """Core-owned checkpoint policy and authoritative tool executor."""

    def __init__(
        self,
        client: BrainProposalClient,
        *,
        system_status_reader: ReadOperation,
        device_list_reader: ReadOperation,
        audit: AuditWriter,
        execution_allowlist: tuple[ToolName, ...] = C4_EXECUTION_ALLOWLIST,
        set_test_led_executor: SetTestLedExecutor | None = None,
        safe_mission_executor: StoredOrchestrationExecutor | None = None,
        safe_automation_executor: StoredOrchestrationExecutor | None = None,
        room_mode_executor: RoomModeExecutor | None = None,
    ) -> None:
        if execution_allowlist not in {
            C4_EXECUTION_ALLOWLIST,
            C5_EXECUTION_ALLOWLIST,
            C6A_EXECUTION_ALLOWLIST,
            C6B_EXECUTION_ALLOWLIST,
            C7_EXECUTION_ALLOWLIST,
        }:
            raise ValueError("unsupported Brain execution allowlist")
        self._client = client
        self._readers: dict[str, ReadOperation] = {
            "system_status": system_status_reader,
            "list_devices": device_list_reader,
        }
        self._audit = audit
        self._execution_allowlist = execution_allowlist
        self._set_test_led_executor = set_test_led_executor
        self._safe_mission_executor = safe_mission_executor
        self._safe_automation_executor = safe_automation_executor
        self._room_mode_executor = room_mode_executor
        if execution_allowlist == C7_EXECUTION_ALLOWLIST:
            self._checkpoint = "c7"
        elif execution_allowlist == C6B_EXECUTION_ALLOWLIST:
            self._checkpoint = "c6b"
        elif execution_allowlist == C6A_EXECUTION_ALLOWLIST:
            self._checkpoint = "c6a"
        elif execution_allowlist == C5_EXECUTION_ALLOWLIST:
            self._checkpoint = "c5"
        else:
            self._checkpoint = "c4"

    def chat(self, request: BrainChatRequest) -> CoreBrainChatResponse:
        self._audit(
            "request_accepted",
            "info",
            {"request_id": request.request_id},
        )
        try:
            untrusted_response = self._client.chat(request)
            # The Brain service/client validation is not trusted. Rebuild the
            # entire C1 response at the Core boundary before any policy check.
            response = BrainChatResponse.model_validate(
                untrusted_response.model_dump(mode="python")
                if isinstance(untrusted_response, BrainChatResponse)
                else untrusted_response
            )
            if response.request_id != request.request_id:
                raise ValueError("request_id mismatch")
        except BrainClientError as error:
            self._audit(
                "request_failed",
                "warning",
                {"request_id": request.request_id, "reason": error.code},
            )
            raise
        except (ValidationError, TypeError, ValueError, AttributeError):
            self._audit(
                "request_failed",
                "warning",
                {
                    "request_id": request.request_id,
                    "reason": "invalid_brain_response",
                },
            )
            raise BrainClientError("invalid_brain_response") from None

        tool_names = [call.name for call in response.tool_calls]
        self._audit(
            "response_received",
            "info",
            {
                "request_id": request.request_id,
                "tool_names": tool_names,
                "tool_count": len(tool_names),
            },
        )

        if request.allowed_tools is not None:
            narrowed_disallowed = [
                call
                for call in response.tool_calls
                if call.name not in request.allowed_tools
            ]
            if narrowed_disallowed:
                self._audit(
                    "narrowed_policy_rejected",
                    "warning",
                    {
                        "request_id": request.request_id,
                        "tool_names": tool_names,
                        "rejected_tool_names": [
                            call.name
                            for call in narrowed_disallowed
                        ],
                        "reason": "tool_not_allowed_by_request",
                    },
                )
                return CoreBrainChatResponse(
                    request_id=response.request_id,
                    assistant_text=response.assistant_text,
                    proposed_tool_calls=response.tool_calls,
                    tool_results=[
                        CoreBrainToolResult(
                            name=call.name,
                            status="rejected",
                            reason=(
                                "tool_not_allowed_by_request"
                                if call.name not in request.allowed_tools
                                else "batch_rejected_by_request"
                            ),
                        )
                        for call in response.tool_calls
                    ],
                )

        disallowed = [
            call for call in response.tool_calls
            if call.name not in self._execution_allowlist
        ]
        if disallowed:
            policy_reason = f"tool_not_enabled_in_{self._checkpoint}"
            batch_reason = f"batch_rejected_in_{self._checkpoint}"
            self._audit(
                "policy_rejected",
                "warning",
                {
                    "request_id": request.request_id,
                    "tool_names": tool_names,
                    "rejected_tool_names": [call.name for call in disallowed],
                    "reason": policy_reason,
                },
            )
            # Atomic checkpoint policy: one valid-but-disabled tool rejects the complete
            # batch, so an allowed read cannot partially execute beside mutation.
            return CoreBrainChatResponse(
                request_id=response.request_id,
                assistant_text=response.assistant_text,
                proposed_tool_calls=response.tool_calls,
                tool_results=[
                    CoreBrainToolResult(
                        name=call.name,
                        status="rejected",
                        reason=(
                            policy_reason
                            if call.name not in self._execution_allowlist
                            else batch_reason
                        ),
                    )
                    for call in response.tool_calls
                ],
            )

        results: list[CoreBrainToolResult] = []
        for call in response.tool_calls:
            if call.name == "set_test_led":
                results.append(
                    self._execute_set_test_led(request.request_id, call)
                )
                continue
            if call.name == "set_room_mode":
                outcome = execute_room_mode_proposal(
                    request_id=request.request_id,
                    call=call,
                    executor=self._room_mode_executor,
                    audit=self._audit,
                )
                results.append(
                    CoreBrainToolResult(
                        name=call.name,
                        status=outcome.status,
                        result=outcome.result,
                        reason=outcome.reason,
                    )
                )
                continue
            if call.name == "run_safe_mission":
                results.append(
                    self._execute_stored_orchestration(
                        request.request_id,
                        call,
                        self._safe_mission_executor,
                        "mission",
                    )
                )
                continue
            if call.name == "run_safe_automation":
                results.append(
                    self._execute_stored_orchestration(
                        request.request_id,
                        call,
                        self._safe_automation_executor,
                        "automation",
                    )
                )
                continue
            outcome = execute_authoritative_read(
                request_id=request.request_id,
                call=call,
                operation=self._readers[call.name],
                audit=self._audit,
            )
            results.append(
                CoreBrainToolResult(
                    name=call.name,
                    status=outcome.status,
                    result=outcome.result,
                    reason=outcome.reason,
                )
            )

        return CoreBrainChatResponse(
            request_id=response.request_id,
            assistant_text=response.assistant_text,
            proposed_tool_calls=response.tool_calls,
            tool_results=results,
        )

    def _execute_set_test_led(
        self,
        request_id: str,
        call: BrainToolCall,
    ) -> CoreBrainToolResult:
        value = call.arguments["value"]
        self._audit(
            "mutation_validated",
            "info",
            {
                "request_id": request_id,
                "tool_name": call.name,
            },
        )
        self._audit(
            "fixed_mapping_selected",
            "info",
            {
                "request_id": request_id,
                "tool_name": call.name,
                **SET_TEST_LED_CORE_MAPPING,
            },
        )
        if self._set_test_led_executor is None:
            self._audit(
                "mutation_result",
                "warning",
                {
                    "request_id": request_id,
                    "tool_name": call.name,
                    "outcome": "error",
                    "failure_category": "mutation_execution_failed",
                },
            )
            return CoreBrainToolResult(
                name=call.name,
                status="error",
                reason="mutation_execution_failed",
            )

        try:
            outcome = self._set_test_led_executor.execute(value)
        except Exception:
            self._audit(
                "mutation_result",
                "warning",
                {
                    "request_id": request_id,
                    "tool_name": call.name,
                    "outcome": "error",
                    "failure_category": "mutation_execution_failed",
                },
            )
            return CoreBrainToolResult(
                name=call.name,
                status="error",
                reason="mutation_execution_failed",
            )

        safety_decision = outcome.audit.get("safety_decision")
        if isinstance(safety_decision, dict):
            self._audit(
                "safety_decision",
                "info" if safety_decision.get("allowed") else "warning",
                {
                    "request_id": request_id,
                    "tool_name": call.name,
                    **safety_decision,
                },
            )
        self._audit(
            "mutation_result",
            (
                "info"
                if outcome.status in {"pending", "confirmed"}
                else "warning"
            ),
            {
                "request_id": request_id,
                "tool_name": call.name,
                **{
                    key: value
                    for key, value in outcome.audit.items()
                    if key != "safety_decision"
                },
            },
        )
        return CoreBrainToolResult(
            name=call.name,
            status=outcome.status,
            result=outcome.result,
            reason=outcome.reason,
        )

    def _execute_stored_orchestration(
        self,
        request_id: str,
        call: BrainToolCall,
        executor: StoredOrchestrationExecutor | None,
        record_type: Literal["mission", "automation"],
    ) -> CoreBrainToolResult:
        failure_reason = f"{record_type}_execution_failed"
        outcome = execute_stored_orchestration(
            request_id=request_id,
            call=call,
            executor=executor,
            record_type=record_type,
            audit=self._audit,
        )
        if outcome is None:
            return CoreBrainToolResult(
                name=call.name,
                status="error",
                reason=failure_reason,
            )
        return CoreBrainToolResult(
            name=call.name,
            status=outcome.status,
            result=outcome.result,
            reason=outcome.reason,
        )
